import base64
import hashlib
import hmac

from django.conf import settings
from django.template import loader
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.translation import gettext

import olympia.core.logger

from olympia import amo
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
        except (ValueError, TypeError):
            # Data is broken
            raise ValueError

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
