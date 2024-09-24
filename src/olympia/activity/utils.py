import re
from datetime import datetime
from email.utils import formataddr
from html import unescape

from django.conf import settings
from django.core.mail.message import sanitize_address
from django.forms import ValidationError
from django.template import loader
from django.urls import reverse
from django.utils import translation

import waffle
from email_reply_parser import EmailReplyParser

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog, ActivityLogToken
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail
from olympia.constants.reviewers import REVIEWER_STANDARD_REPLY_TIME
from olympia.reviewers.models import NeedsHumanReview
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.utils import get_review_due_date


log = olympia.core.logger.getLogger('z.amo.activity')

# Prefix of the reply to address in devcomm emails.
REPLY_TO_PREFIX = 'reviewreply+'
# Group for users that want a copy of all Activity Emails.
ACTIVITY_MAIL_GROUP = 'Activity Mail CC'
SOCKETLABS_SPAM_THRESHOLD = 10.0
# Types of users who might be sending or receiving emails.
USER_TYPE_ADDON_AUTHOR = 1
USER_TYPE_ADDON_REVIEWER = 2
ADDON_REVIEWER_NAME = 'An add-on reviewer'


class ActivityEmailError(ValueError):
    pass


class ActivityEmailEncodingError(ActivityEmailError):
    pass


class ActivityEmailUUIDError(ActivityEmailError):
    pass


class ActivityEmailTokenError(ActivityEmailError):
    pass


class ActivityEmailToNotificationsError(ActivityEmailError):
    pass


class ActivityEmailParser:
    """Utility to parse email replies."""

    address_prefix = REPLY_TO_PREFIX

    def __init__(self, message):
        invalid_email = not isinstance(message, dict) or not message.get(
            'TextBody', None
        )

        if invalid_email:
            log.warning("ActivityEmailParser didn't get a valid message.")
            raise ActivityEmailEncodingError(
                'Invalid or malformed json message object.'
            )

        self.email = message
        reply = self._extra_email_reply_parse(self.email['TextBody'])
        self.reply = EmailReplyParser.read(reply).reply

    def _extra_email_reply_parse(self, email):
        """
        Adds an extra case to the email reply parser where the reply is
        followed by headers like "From: nobody@mozilla.org" and
        strips that part out.
        """
        email_header_re = re.compile(r'From: [^@]+@[^@]+\.[^@]+')
        split_email = email_header_re.split(email)
        if split_email[0].startswith('From: '):
            # In case, it's a bottom reply, return everything.
            return email
        else:
            # Else just return the email reply portion.
            return split_email[0]

    def get_uuid(self):
        recipients = self.email.get('To', None) or []
        addresses = [to.get('EmailAddress', '') for to in recipients]
        for address in addresses:
            if address.startswith(self.address_prefix):
                # Strip everything between "reviewreply+" and the "@" sign.
                return address[len(self.address_prefix) :].split('@')[0]
        log.debug(
            'TO: address missing or not related to activity emails. (%s)',
            ', '.join(addresses),
        )
        raise ActivityEmailUUIDError(
            'TO: address does not contain activity email uuid (%s).'
            % ', '.join(addresses)
        )


def add_email_to_activity_log_wrapper(message, spam_rating):
    note = None
    # Strings all untranslated as we don't know the locale of the email sender.
    reason = 'Undefined Error.'
    try:
        parser = ActivityEmailParser(message)
        note = add_email_to_activity_log(parser)
    except ActivityEmailError as exception:
        reason = str(exception)

    if not note and waffle.switch_is_active('activity-email-bouncing'):
        try:
            spam_rating = float(spam_rating)
        except ValueError:
            spam_rating = 0.0
        if spam_rating < SOCKETLABS_SPAM_THRESHOLD:
            try:
                bounce_mail(message, reason)
            except Exception:
                log.exception('Bouncing invalid email failed.')
        else:
            log.info(f'Skipping email bounce because probable spam ({spam_rating})')
    return note


def add_email_to_activity_log(parser):
    log.info('Saving from email reply')
    uuid = parser.get_uuid()
    try:
        token = ActivityLogToken.objects.get(uuid=uuid)
    except (ActivityLogToken.DoesNotExist, ValidationError) as exc:
        log.warning('An email was skipped with non-existing uuid %s.', uuid)
        raise ActivityEmailUUIDError(
            'UUID found in email address TO: header but is not a valid token '
            '(%s).' % uuid
        ) from exc

    version = token.version
    user = token.user
    if user.banned is None:
        if token.is_valid():
            log_type = action_from_user(user, version)

            if log_type:
                note = log_and_notify(log_type, parser.reply, user, version)
                log.info(
                    'A new note has been created (from %s using '
                    'tokenid %s).' % (user.id, uuid)
                )
                token.increment_use()
                return note
            else:
                log.warning(
                    '%s did not have perms to reply to email thread %s.',
                    user.email,
                    version.id,
                )
                raise ActivityEmailTokenError(
                    "You don't have permission to reply to this add-on. You "
                    'have to be a listed developer currently, or an AMO '
                    'reviewer.'
                )
        else:
            log.warning(
                '%s tried to use an invalid activity email token for version %s.',
                user.email,
                version.id,
            )
            reason = (
                "it's for a non-existing version of the addon"
                if not token.is_expired()
                else 'there have been too many replies'
            )
            raise ActivityEmailTokenError(
                "You can't reply to this email as the reply token is no "
                'longer valid because %s.' % reason
            )
    else:
        log.info(
            'Ignored email reply from banned user %s for version %s.'
            % (user.id, version.id)
        )
        raise ActivityEmailError('Your account is not allowed to send replies.')


def type_of_user(user, version):
    if version.addon.authors.filter(pk=user.pk).exists():
        return USER_TYPE_ADDON_AUTHOR
    if acl.is_user_any_kind_of_reviewer(user):
        return USER_TYPE_ADDON_REVIEWER


def action_from_user(user, version):
    if type_of_user(user, version) == USER_TYPE_ADDON_AUTHOR:
        return amo.LOG.DEVELOPER_REPLY_VERSION
    if type_of_user(user, version) == USER_TYPE_ADDON_REVIEWER:
        return amo.LOG.REVIEWER_REPLY_VERSION


def template_from_user(user, version):
    template = 'activity/emails/developer.txt'
    if (
        type_of_user(user, version) != USER_TYPE_ADDON_AUTHOR
        and type_of_user(user, version) == USER_TYPE_ADDON_REVIEWER
    ):
        template = 'activity/emails/from_reviewer.txt'
    return loader.get_template(template)


def log_and_notify(
    action, comments, note_creator, version, perm_setting=None, detail_kwargs=None
):
    """Record an action through ActivityLog and notify relevant users about it."""
    log_kwargs = {
        'user': note_creator,
        'created': datetime.now(),
    }
    if detail_kwargs is None:
        detail_kwargs = {}
    if comments:
        detail_kwargs['version'] = version.version
        detail_kwargs['comments'] = comments
    if detail_kwargs:
        log_kwargs['details'] = detail_kwargs

    if action == amo.LOG.DEVELOPER_REPLY_VERSION:
        had_due_date = bool(version.due_date)
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
        )
        if not had_due_date:
            version.update(
                due_date=get_review_due_date(default_days=REVIEWER_STANDARD_REPLY_TIME)
            )

    note = ActivityLog.objects.create(action, version.addon, version, **log_kwargs)
    if not note:
        return

    notify_about_activity_log(version.addon, version, note, perm_setting=perm_setting)
    return note


def notify_about_activity_log(
    addon, version, note, perm_setting=None, send_to_staff=True
):
    """Notify relevant users about an ActivityLog note."""
    comments = (note.details or {}).get('comments')
    if not comments:
        # Just use the name of the action if no comments provided.  Alas we
        # can't know the locale of recipient, and our templates are English
        # only so prevent language jumble by forcing into en-US.
        with translation.override(settings.LANGUAGE_CODE):
            comments = '%s' % amo.LOG_BY_ID[note.action].short
    else:
        comments = unescape(comments)

    type_of_sender = type_of_user(note.user, version)
    sender_name = (
        ADDON_REVIEWER_NAME
        if type_of_sender == USER_TYPE_ADDON_REVIEWER
        else note.user.name
    )

    # Collect add-on authors (excl. the person who sent the email.) and build
    # the context for them.
    addon_authors = set(addon.authors.all()) - {note.user}

    author_context_dict = {
        'name': addon.name,
        'number': version.version,
        'author': sender_name,
        'comments': comments,
        'has_attachment': hasattr(note, 'attachmentlog'),
        'url': absolutify(addon.get_dev_url('versions')),
        'SITE_URL': settings.SITE_URL,
        'email_reason': 'you are listed as an author of this add-on',
    }

    # Not being localised because we don't know the recipients locale.
    with translation.override('en-US'):
        subject = reviewer_subject = 'Mozilla Add-ons: {} {}'.format(
            addon.name,
            version.version,
        )
    # Build and send the mail for authors.
    template = template_from_user(note.user, version)
    from_email = formataddr((sender_name, settings.ADDONS_EMAIL))
    send_activity_mail(
        subject,
        template.render(author_context_dict),
        version,
        addon_authors,
        from_email,
        note.id,
        perm_setting,
    )

    if send_to_staff:
        # If task_user doesn't exist that's no big issue (i.e. in tests)
        try:
            task_user = {get_task_user()}
        except UserProfile.DoesNotExist:
            task_user = set()
        # Update the author and from_email to use the real name because it will
        # be used in emails to reviewers and staff, and not add-on developers.
        from_email = formataddr((note.user.name, settings.ADDONS_EMAIL))

        # Collect staff that want a copy of the email, build the context for
        # them and send them their copy.
        staff = set(UserProfile.objects.filter(groups__name=ACTIVITY_MAIL_GROUP))
        staff_cc = staff - addon_authors - task_user - {note.user}
        staff_cc_context_dict = author_context_dict.copy()
        staff_cc_context_dict['author'] = note.user.name
        staff_cc_context_dict['url'] = absolutify(
            reverse(
                'reviewers.review',
                kwargs={
                    'addon_id': version.addon.pk,
                    'channel': amo.CHANNEL_CHOICES_API[version.channel],
                },
                add_prefix=False,
            )
        )
        staff_cc_context_dict['email_reason'] = (
            'you are member of the activity email cc group'
        )
        send_activity_mail(
            reviewer_subject,
            template.render(staff_cc_context_dict),
            version,
            staff_cc,
            from_email,
            note.id,
            perm_setting,
        )


def send_activity_mail(
    subject, message, version, recipients, from_email, unique_id, perm_setting=None
):
    thread_id = f'{version.addon.id}/{version.id}'
    reference_header = '<{thread}@{site}>'.format(
        thread=thread_id, site=settings.INBOUND_EMAIL_DOMAIN
    )
    message_id = '<{thread}/{message}@{site}>'.format(
        thread=thread_id, message=unique_id, site=settings.INBOUND_EMAIL_DOMAIN
    )
    headers = {
        'In-Reply-To': reference_header,
        'References': reference_header,
        'Message-ID': message_id,
    }

    for recipient in recipients:
        token, created = ActivityLogToken.objects.get_or_create(
            version=version, user=recipient
        )
        if not created:
            token.update(use_count=0)
        else:
            log.info(f'Created token with UUID {token.uuid} for user: {recipient.id}.')
        reply_to = '{}{}@{}'.format(
            REPLY_TO_PREFIX,
            token.uuid.hex,
            settings.INBOUND_EMAIL_DOMAIN,
        )
        log.info(
            'Sending activity email to %s for %s version %s'
            % (recipient, version.addon.pk, version.pk)
        )
        send_mail(
            subject,
            message,
            recipient_list=[recipient.email],
            from_email=from_email,
            use_deny_list=False,
            headers=headers,
            perm_setting=perm_setting,
            reply_to=[reply_to],
        )


def bounce_mail(message, reason):
    recipient_header = (
        None
        if not isinstance(message, dict)
        else message.get('From', message.get('ReplyTo'))
    )
    if not recipient_header:
        log.warning(
            'Tried to bounce incoming activity mail but no From or '
            'ReplyTo header present.'
        )
        return
    recipient = recipient_header.get('EmailAddress')
    try:
        recipient = sanitize_address(
            recipient_header.get('EmailAddress'), settings.DEFAULT_CHARSET
        )
    except ValueError:
        log.warning('Tried to bounce incoming activity mail but recipient is invalid')
        return

    body = loader.get_template('activity/emails/bounce.txt').render(
        {'reason': reason, 'SITE_URL': settings.SITE_URL}
    )
    send_mail(
        'Re: %s' % message.get('Subject', 'your email to us'),
        body,
        recipient_list=[recipient],
        use_deny_list=False,
    )
