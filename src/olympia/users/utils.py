import base64
import datetime
import hashlib
import hmac
import urllib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import loader
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.translation import gettext

import requests
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import activity, amo, core
from olympia.activity import log_create


log = olympia.core.logger.getLogger('z.users')


class UnsubscribeCode:
    @classmethod
    def create(cls, email):
        """Encode+Hash an email for an unsubscribe code."""
        # Need to make sure email is in bytes to make b64encoding and hmac.new
        # work.
        email = force_bytes(email)
        secret = cls.make_secret(email)
        return base64.urlsafe_b64encode(email), secret

    @classmethod
    def parse(cls, code, hash):
        try:
            decoded = base64.urlsafe_b64decode(force_bytes(code))
            email = decoded
        except (ValueError, TypeError) as exc:
            # Data is broken
            raise ValueError from exc

        if cls.make_secret(decoded) != hash:
            log.info('[Tampering] Unsubscribe link data does not match hash')
            raise ValueError

        return force_str(email)

    @classmethod
    def make_secret(cls, token):
        return hmac.new(
            force_bytes(settings.SECRET_KEY), msg=token, digestmod=hashlib.sha256
        ).hexdigest()


def get_task_user():
    """
    Returns a user object. This user is suitable for assigning to
    cron jobs or long running tasks.
    """
    from olympia.users.models import UserProfile

    return UserProfile.objects.get(pk=settings.TASK_USER_ID)


def mail_addon_author_changes(
    author, title, template_part, recipients, action=None, extra_context=None
):
    from olympia.amo.utils import send_mail

    context_data = {
        'author': author,
        'addon': author.addon,
        'DOMAIN': settings.DOMAIN,
        **(extra_context or {}),
    }
    template = loader.get_template(f'users/emails/{template_part}.ltxt')
    send_mail(
        title, template.render(context_data), None, recipients, use_deny_list=False
    )
    if action:
        log_create(action, author.user, author.get_role_display(), author.addon)


def send_addon_author_add_mail(addon_user, existing_authors_emails):
    from olympia.amo.templatetags.jinja_helpers import absolutify

    mail_addon_author_changes(
        author=addon_user,
        title=gettext('An author has been added to your add-on'),
        template_part='author_added',
        recipients=list(existing_authors_emails),
        action=amo.LOG.ADD_USER_WITH_ROLE,
    )
    mail_addon_author_changes(
        author=addon_user,
        title=gettext('Author invitation for {addon_name}').format(
            addon_name=str(addon_user.addon.name)
        ),
        template_part='author_added_confirmation',
        recipients=[addon_user.user.email],
        action=None,
        extra_context={
            'author_confirmation_link': absolutify(
                reverse('devhub.addons.invitation', args=(addon_user.addon.slug,))
            )
        },
    )


def send_addon_author_change_mail(addon_user, existing_authors_emails):
    mail_addon_author_changes(
        author=addon_user,
        title=gettext('An author role has been changed on your add-on'),
        template_part='author_changed',
        recipients=list({*existing_authors_emails, addon_user.user.email}),
        action=amo.LOG.CHANGE_USER_WITH_ROLE,
    )


def send_addon_author_remove_mail(addon_user, existing_authors_emails):
    mail_addon_author_changes(
        author=addon_user,
        title=gettext('An author has been removed from your add-on'),
        template_part='author_removed',
        recipients=list({*existing_authors_emails, addon_user.user.email}),
        action=amo.LOG.REMOVE_USER_WITH_ROLE,
    )


class RestrictionChecker:
    """
    Wrapper around all our submission and approval restriction classes.

    To use, instantiate it with the request and call is_submission_allowed(),
    or with None as the request and is_auto_approval_allowed() for approval after
    submission.
    After this method has been called, the error message to show the user if
    needed will be available through get_error_message()
    """

    def __init__(self, *, request=None, upload=None):
        self.request = request
        self.upload = upload
        if self.request:
            self.user = self.request.user
            self.ip_address = self.request.META.get('REMOTE_ADDR', '')
            self.request_metadata = core.select_request_fingerprint_headers(
                request.headers
            )
        elif self.upload:
            self.user = self.upload.user
            self.ip_address = self.upload.ip_address
            self.request_metadata = self.upload.request_metadata
        else:
            raise ImproperlyConfigured('RestrictionChecker needs a request or upload')
        self.failed_restrictions = []

    def _is_action_allowed(self, action_type, *, restriction_choices=None):
        from olympia.users.models import UserRestrictionHistory

        if restriction_choices is None:
            # We use UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES because it
            # currently matches the order we want to check things. If that ever
            # changes, keep RESTRICTION_CLASSES_CHOICES current order (to keep existing
            # records intact) but change the `restriction_choices` definition below.
            restriction_choices = UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES
        # Default to self.request because most action_types expect it
        argument = self.upload if action_type == 'auto_approval' else self.request
        for restriction_number, cls in restriction_choices:
            if not hasattr(cls, f'allow_{action_type}'):
                continue
            allowed_method = getattr(cls, f'allow_{action_type}', None)
            if allowed_method is None:
                continue
            allowed = allowed_method(argument)
            if not allowed:
                self.failed_restrictions.append(cls)
                name = cls.__name__
                statsd.incr(
                    f'RestrictionChecker.is_{action_type}_allowed.{name}.failure'
                )
                if self.user and self.user.is_authenticated:
                    with core.override_remote_addr_or_metadata(
                        ip_address=self.ip_address, metadata=self.request_metadata
                    ):
                        activity.log_create(
                            amo.LOG.RESTRICTED,
                            user=self.user,
                            details={'restriction': str(cls.__name__)},
                        )
                    UserRestrictionHistory.objects.create(
                        user=self.user,
                        ip_address=self.ip_address,
                        last_login_ip=self.user.last_login_ip or '',
                        restriction=restriction_number,
                    )
        suffix = 'success' if not self.failed_restrictions else 'failure'
        statsd.incr(f'RestrictionChecker.is_{action_type}_allowed.%s' % suffix)
        return not self.failed_restrictions

    def is_submission_allowed(self, check_dev_agreement=True):
        """
        Check whether the `request` passed to the instance is allowed to submit add-ons.
        Will check all classes declared in self.restriction_classes, but ignore those
        that don't have a allow_submission() method.

        Pass check_dev_agreement=False to avoid checking
        DeveloperAgreementRestriction class, which is useful only for the
        developer agreement page itself, where the developer hasn't validated
        the agreement yet but we want to do the other checks anyway.
        """
        from olympia.users.models import (
            DeveloperAgreementRestriction,
            UserRestrictionHistory,
        )

        if not self.request:
            raise ImproperlyConfigured('Need a request to call is_submission_allowed()')

        if self.user and self.user.bypass_upload_restrictions:
            return True

        if check_dev_agreement is False:
            restriction_choices = filter(
                lambda item: item[1] != DeveloperAgreementRestriction,
                UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES,
            )
        else:
            restriction_choices = None
        return self._is_action_allowed(
            'submission', restriction_choices=restriction_choices
        )

    def is_auto_approval_allowed(self):
        """
        Check whether the `upload` passed to the instance is allowed auto-approval.
        Will check all classes declared in self.restriction_classes, but ignore those
        that don't have a allow_auto_approval() method.
        """

        if not self.upload:
            raise ImproperlyConfigured(
                'Need an upload to call is_auto_approval_allowed()'
            )

        return self._is_action_allowed('auto_approval')

    def is_rating_allowed(self):
        """
        Check whether the `request` passed to the instance is allowed to submit a
        rating. Will check all classes declared in self.restriction_classes, but ignore
        those that don't have a allow_rating() method.
        """
        return self._is_action_allowed('rating')

    def should_moderate_rating(self):
        """
        Check whether the `request` passed to the instance should have ratings
        moderated. Will check all classes declared in self.restriction_classes, but
        ignore those that don't have a allow_rating_without_moderation() method.
        """
        return not self._is_action_allowed('rating_without_moderation')

    def get_error_message(self):
        """
        Return the error message to show to the user after a call to
        is_submission_allowed_for_request() has been made. Will return the
        message to be displayed to the user, or None if there is no specific
        restriction applying.
        """
        try:
            msg = self.failed_restrictions[0].get_error_message(
                is_api=self.request and self.request.is_api
            )
        except IndexError:
            msg = None
        return msg


def upload_picture(user, picture):
    from olympia.users.tasks import resize_photo

    original = user.picture_path_original

    storage = amo.utils.SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
    with storage.open(original, 'wb') as original_file:
        for chunk in picture.chunks():
            original_file.write(chunk)
    user.update(picture_type=picture.content_type)
    resize_photo.delay(
        original,
        user.picture_path,
        set_modified_on=user.serializable_reference(),
    )


def assert_socket_labs_settings_defined():
    if not settings.SOCKET_LABS_TOKEN:
        raise Exception('SOCKET_LABS_TOKEN is not defined')

    if not settings.SOCKET_LABS_HOST:
        raise Exception('SOCKET_LABS_HOST is not defined')

    if not settings.SOCKET_LABS_SERVER_ID:
        raise Exception('SOCKET_LABS_SERVER_ID is not defined')


utils_log = olympia.core.logger.getLogger('z.users')


def check_suppressed_email_confirmation(verification, page_size=5):
    from olympia.users.models import SuppressedEmailVerification

    assert_socket_labs_settings_defined()

    assert isinstance(verification, SuppressedEmailVerification)

    email = verification.suppressed_email.email

    current_count = 0
    total = 0

    code_snippet = str(verification.confirmation_code)[-5:]
    path = f'servers/{settings.SOCKET_LABS_SERVER_ID}/reports/recipient-search/'

    # socketlabs might set the queued time any time of day
    # so we need to check to midnight, one day before the verification was created
    # and to midnight of tomorrow
    before = verification.created - datetime.timedelta(days=1)
    start_date = datetime.datetime(
        year=before.year,
        month=before.month,
        day=before.day,
    )
    end_date = datetime.datetime.now() + datetime.timedelta(days=1)
    date_format = '%Y-%m-%d'

    params = {
        'toEmailAddress': email,
        'startDate': start_date.strftime(date_format),
        'endDate': end_date.strftime(date_format),
        'pageNumber': 0,
        'pageSize': page_size,
        'sortField': 'queuedTime',
        'sortDirection': 'dsc',
    }

    is_first_page = True

    found_emails = []

    while current_count < total or is_first_page:
        if not is_first_page:
            params['pageNumber'] = params['pageNumber'] + 1

        url = (
            urllib.parse.urljoin(settings.SOCKET_LABS_HOST, path)
            + '?'
            + urllib.parse.urlencode(params)
        )

        headers = {
            'authorization': f'Bearer {settings.SOCKET_LABS_TOKEN}',
        }

        utils_log.info(f'checking for {code_snippet} with params {params}')

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        json_data = response.json()

        utils_log.info(f'recieved data {json_data} for {code_snippet}')

        if is_first_page:
            total = json_data['total']

            if total == 0:
                return found_emails

            is_first_page = False

        data = json_data['data']
        current_count += len(data)

        utils_log.info(f'found emails {data} for {code_snippet}')

        ## TODO: check if we can set `customMessageId` to replace code snippet
        for item in data:
            found_emails.append(
                {
                    'from': item['from'],
                    'to': item['to'],
                    'subject': item['subject'],
                    'status': item['status'],
                    'statusDate': item['statusDate'],
                }
            )

            if code_snippet in item['subject'] and item['status'] == 'Delivered':
                verification.mark_as_delivered()

    return found_emails
