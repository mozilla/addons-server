import datetime
import logging
import re

from django.conf import settings
from django.template import Context, loader

from email_reply_parser import EmailReplyParser
import waffle

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLogToken
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.devhub.models import ActivityLog
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user

log = logging.getLogger('z.amo.activity')

# Prefix of the reply to address in devcomm emails.
REPLY_TO_PREFIX = 'reviewreply+'
# Group for users that want a copy of all Activity Emails.
ACTIVITY_MAIL_GROUP = 'Activity Mail CC'


class ActivityEmailError(ValueError):
    pass


class ActivityEmailEncodingError(ActivityEmailError):
    pass


class ActivityEmailUUIDError(ActivityEmailError):
    pass


class ActivityEmailTokenError(ActivityEmailError):
    pass


class ActivityEmailParser(object):
    """Utility to parse email replies."""
    address_prefix = REPLY_TO_PREFIX

    def __init__(self, message):
        if (not isinstance(message, dict) or 'TextBody' not in message):
            log.exception('ActivityEmailParser didn\'t get a valid message.')
            raise ActivityEmailEncodingError(
                'Invalid or malformed json message object.')

        self.email = message
        reply = self._extra_email_reply_parse(self.email['TextBody'])
        self.reply = EmailReplyParser.read(reply).reply

    def _extra_email_reply_parse(self, email):
        """
        Adds an extra case to the email reply parser where the reply is
        followed by headers like "From: amo-editors@mozilla.org" and
        strips that part out.
        """
        email_header_re = re.compile('From: [^@]+@[^@]+\.[^@]+')
        split_email = email_header_re.split(email)
        if split_email[0].startswith('From: '):
            # In case, it's a bottom reply, return everything.
            return email
        else:
            # Else just return the email reply portion.
            return split_email[0]

    def get_uuid(self):
        to_header = self.email.get('To', [])
        for to in to_header:
            address = to.get('EmailAddress', '')
            if address.startswith(self.address_prefix):
                # Strip everything between "reviewreply+" and the "@" sign.
                return address[len(self.address_prefix):].split('@')[0]
        log.exception(
            'TO: address missing or not related to activity emails. (%s)'
            % to_header)
        raise ActivityEmailUUIDError(
            'TO: address doesn\'t contain activity email uuid (%s).'
            % to_header)


def add_email_to_activity_log_wrapper(message):
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
            bounce_mail(message, reason)
        except Exception:
            log.error('Bouncing invalid email failed.')
    return note


def add_email_to_activity_log(parser):
    log.debug("Saving from email reply")
    uuid = parser.get_uuid()
    try:
        token = ActivityLogToken.objects.get(uuid=uuid)
    except ActivityLogToken.DoesNotExist:
        log.error('An email was skipped with non-existing uuid %s.' % uuid)
        raise ActivityEmailUUIDError(
            'UUID found in email address TO: header but is not a valid token '
            '(%s).' % uuid)

    version = token.version
    user = token.user
    if token.is_valid():
        log_type = action_from_user(user, version)

        if log_type:
            note = log_and_notify(log_type, parser.reply, user, version)
            log.info('A new note has been created (from %s using tokenid %s).'
                     % (user.id, uuid))
            token.increment_use()
            return note
        else:
            log.error('%s did not have perms to reply to email thread %s.'
                      % (user.email, version.id))
            raise ActivityEmailTokenError(
                'You don\'t have permission to reply to this add-on. You '
                'have to be a listed developer currently, or an AMO reviewer.')
    else:
        log.error('%s tried to use an invalid activity email token for '
                  'version %s.' % (user.email, version.id))
        reason = ('it\'s for an old version of the addon'
                  if not token.is_expired() else
                  'there have been too many replies')
        raise ActivityEmailTokenError(
            'You can\'t reply to this email as the reply token is no longer'
            'valid because %s.' % reason)


def action_from_user(user, version):
    review_perm = 'Review' if version.addon.is_listed else 'ReviewUnlisted'
    if version.addon.authors.filter(pk=user.pk).exists():
        return amo.LOG.DEVELOPER_REPLY_VERSION
    elif acl.action_allowed_user(user, 'Addons', review_perm):
        return amo.LOG.REVIEWER_REPLY_VERSION


def log_and_notify(action, comments, note_creator, version):
    log_kwargs = {
        'user': note_creator,
        'created': datetime.datetime.now(),
        'details': {
            'comments': comments,
            'version': version.version}}
    note = amo.log(action, version.addon, version, **log_kwargs)

    # Collect reviewers/others involved with this version.
    log_users = {
        alog.user for alog in ActivityLog.objects.for_version(version)}
    # Collect add-on authors (excl. the person who sent the email.)
    addon_authors = set(version.addon.authors.all()) - {note_creator}
    # Collect staff that want a copy of the email
    staff_cc = set(
        UserProfile.objects.filter(groups__name=ACTIVITY_MAIL_GROUP))
    # If task_user doesn't exist that's no big issue (i.e. in tests)
    try:
        task_user = {get_task_user()}
    except UserProfile.DoesNotExist:
        task_user = set()
    # Collect reviewers on the thread (excl. the email sender and task user for
    # automated messages).
    reviewers = ((log_users | staff_cc) - addon_authors - task_user -
                 {note_creator})
    author_context_dict = {
        'name': version.addon.name,
        'number': version.version,
        'author': note_creator.name,
        'comments': comments,
        'url': version.addon.get_dev_url('versions'),
        'SITE_URL': settings.SITE_URL,
    }
    reviewer_context_dict = author_context_dict.copy()
    reviewer_context_dict['url'] = absolutify(
        reverse('editors.review', args=[version.addon.pk], add_prefix=False))

    # Not being localised because we don't know the recipients locale.
    subject = 'Mozilla Add-ons: %s Updated' % version.addon.name
    template = loader.get_template('activity/emails/developer.txt')
    send_activity_mail(
        subject, template.render(Context(author_context_dict)), version,
        addon_authors, settings.EDITORS_EMAIL)
    send_activity_mail(
        subject, template.render(Context(reviewer_context_dict)), version,
        reviewers, settings.EDITORS_EMAIL)
    return note


def send_activity_mail(subject, message, version, recipients, from_email,
                       perm_setting=None):
    for recipient in recipients:
        token, created = ActivityLogToken.objects.get_or_create(
            version=version, user=recipient)
        if not created:
            token.update(use_count=0)
        else:
            # We need .uuid to be a real UUID not just a str.
            token.reload()
            log.info('Created token with UUID %s for user: %s.' % (
                token.uuid, recipient.id))
        reply_to = "%s%s@%s" % (
            REPLY_TO_PREFIX, token.uuid.hex, settings.INBOUND_EMAIL_DOMAIN)
        log.info('Sending activity email to %s for %s version %s' % (
            recipient, version.addon.pk, version.pk))
        send_mail(
            subject, message, recipient_list=[recipient.email],
            from_email=from_email, use_blacklist=False,
            perm_setting=perm_setting, reply_to=[reply_to])


NOT_PENDING_IDS = (
    amo.LOG.DEVELOPER_REPLY_VERSION.id,
    amo.LOG.APPROVE_VERSION.id,
    amo.LOG.REJECT_VERSION.id,
    amo.LOG.PRELIMINARY_VERSION.id,
    amo.LOG.PRELIMINARY_ADDON_MIGRATED.id,
)


def filter_queryset_to_pending_replies(queryset, log_type_ids=NOT_PENDING_IDS):
    latest_reply = queryset.filter(action__in=log_type_ids).first()
    if not latest_reply:
        return queryset
    return queryset.filter(created__gt=latest_reply.created)


def bounce_mail(message, reason):
    recipient = (None if not isinstance(message, dict)
                 else message.get('From', message.get('ReplyTo')))
    if not recipient:
        log.error('Tried to bounce incoming activity mail but no From or '
                  'ReplyTo header present.')
        return

    body = (loader.get_template('activity/emails/bounce.txt').
            render(Context({'reason': reason, 'SITE_URL': settings.SITE_URL})))
    send_mail(
        'Re: %s' % message.get('Subject', 'your email to us'),
        body,
        recipient_list=[recipient['EmailAddress']],
        from_email=settings.EDITORS_EMAIL,
        use_blacklist=False)
