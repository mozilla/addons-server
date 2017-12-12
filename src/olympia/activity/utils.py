import datetime
import re
from email.utils import formataddr

from django.forms import ValidationError
from django.conf import settings
from django.template import loader
from django.utils import translation

from email_reply_parser import EmailReplyParser
import waffle

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog, ActivityLogToken
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import no_translation, send_mail
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user

log = olympia.core.logger.getLogger('z.amo.activity')

# Prefix of the reply to address in devcomm emails.
REPLY_TO_PREFIX = 'reviewreply+'
# Group for users that want a copy of all Activity Emails.
ACTIVITY_MAIL_GROUP = 'Activity Mail CC'
NOTIFICATIONS_FROM_EMAIL = 'notifications@%s' % settings.INBOUND_EMAIL_DOMAIN


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
        recipients = self.email.get('To', None) or []
        addresses = [to.get('EmailAddress', '') for to in recipients]
        to_notifications_alias = False
        for address in addresses:
            if address.startswith(self.address_prefix):
                # Strip everything between "reviewreply+" and the "@" sign.
                return address[len(self.address_prefix):].split('@')[0]
            elif address == NOTIFICATIONS_FROM_EMAIL:
                # Someone sent an email to notifications@
                to_notifications_alias = True
        if to_notifications_alias:
            log.exception('TO: notifications email used (%s)'
                          % ', '.join(addresses))
            raise ActivityEmailToNotificationsError(
                'This email address is not meant to receive emails directly. '
                'If you want to get in contact with add-on reviewers, please '
                'reply to the original email or join us in IRC on '
                'irc.mozilla.org/#addon-reviewers. Thank you.')
        log.exception(
            'TO: address missing or not related to activity emails. (%s)'
            % ', '.join(addresses))
        raise ActivityEmailUUIDError(
            'TO: address does not contain activity email uuid (%s).'
            % ', '.join(addresses))


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
    except (ActivityLogToken.DoesNotExist, ValidationError):
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
    review_perm = (amo.permissions.ADDONS_REVIEW
                   if version.channel == amo.RELEASE_CHANNEL_LISTED
                   else amo.permissions.ADDONS_REVIEW_UNLISTED)
    if version.addon.authors.filter(pk=user.pk).exists():
        return amo.LOG.DEVELOPER_REPLY_VERSION
    elif acl.action_allowed_user(user, review_perm):
        return amo.LOG.REVIEWER_REPLY_VERSION


def template_from_user(user, version):
    review_perm = (amo.permissions.ADDONS_REVIEW
                   if version.channel == amo.RELEASE_CHANNEL_LISTED
                   else amo.permissions.ADDONS_REVIEW_UNLISTED)
    template = 'activity/emails/developer.txt'
    if (not version.addon.authors.filter(pk=user.pk).exists() and
            acl.action_allowed_user(user, review_perm)):
        template = 'activity/emails/from_reviewer.txt'
    return loader.get_template(template)


def log_and_notify(action, comments, note_creator, version, perm_setting=None,
                   detail_kwargs=None):
    log_kwargs = {
        'user': note_creator,
        'created': datetime.datetime.now(),
    }
    if detail_kwargs is None:
        detail_kwargs = {}
    if comments:
        detail_kwargs['version'] = version.version
        detail_kwargs['comments'] = comments
    else:
        # Just use the name of the action if no comments provided.  Alas we
        # can't know the locale of recipient, and our templates are English
        # only so prevent language jumble by forcing into en-US.
        with no_translation():
            comments = '%s' % action.short
    if detail_kwargs:
        log_kwargs['details'] = detail_kwargs

    note = ActivityLog.create(action, version.addon, version, **log_kwargs)
    if not note:
        return

    # Collect reviewers involved with this version.
    review_perm = (amo.permissions.ADDONS_REVIEW
                   if version.channel == amo.RELEASE_CHANNEL_LISTED
                   else amo.permissions.ADDONS_REVIEW_UNLISTED)
    log_users = {
        alog.user for alog in ActivityLog.objects.for_version(version) if
        acl.action_allowed_user(alog.user, review_perm)}
    # Collect add-on authors (excl. the person who sent the email.)
    addon_authors = set(version.addon.authors.all()) - {note_creator}
    # Collect staff that want a copy of the email
    staff = set(
        UserProfile.objects.filter(groups__name=ACTIVITY_MAIL_GROUP))
    # If task_user doesn't exist that's no big issue (i.e. in tests)
    try:
        task_user = {get_task_user()}
    except UserProfile.DoesNotExist:
        task_user = set()
    # Collect reviewers on the thread (excl. the email sender and task user for
    # automated messages).
    reviewers = log_users - addon_authors - task_user - {note_creator}
    staff_cc = staff - reviewers - addon_authors - task_user - {note_creator}
    author_context_dict = {
        'name': version.addon.name,
        'number': version.version,
        'author': note_creator.name,
        'comments': comments,
        'url': absolutify(version.addon.get_dev_url('versions')),
        'SITE_URL': settings.SITE_URL,
        'email_reason': 'you are an author of this add-on'
    }

    reviewer_context_dict = author_context_dict.copy()
    reviewer_context_dict['url'] = absolutify(
        reverse('reviewers.review',
                kwargs={'addon_id': version.addon.pk,
                        'channel': amo.CHANNEL_CHOICES_API[version.channel]},
                add_prefix=False))
    reviewer_context_dict['email_reason'] = 'you reviewed this add-on'

    staff_cc_context_dict = reviewer_context_dict.copy()
    staff_cc_context_dict['email_reason'] = (
        'you are member of the activity email cc group')

    # Not being localised because we don't know the recipients locale.
    with translation.override('en-US'):
        subject = u'Mozilla Add-ons: %s %s' % (
            version.addon.name, version.version)
    template = template_from_user(note_creator, version)
    from_email = formataddr((note_creator.name, NOTIFICATIONS_FROM_EMAIL))
    send_activity_mail(
        subject, template.render(author_context_dict),
        version, addon_authors, from_email, note.id, perm_setting)

    send_activity_mail(
        subject, template.render(reviewer_context_dict),
        version, reviewers, from_email, note.id, perm_setting)

    send_activity_mail(
        subject, template.render(staff_cc_context_dict),
        version, staff_cc, from_email, note.id, perm_setting)

    if action == amo.LOG.DEVELOPER_REPLY_VERSION:
        version.update(has_info_request=False)

    return note


def send_activity_mail(subject, message, version, recipients, from_email,
                       unique_id, perm_setting=None):
    thread_id = '{addon}/{version}'.format(
        addon=version.addon.id, version=version.id)
    reference_header = '<{thread}@{site}>'.format(
        thread=thread_id, site=settings.INBOUND_EMAIL_DOMAIN)
    message_id = '<{thread}/{message}@{site}>'.format(
        thread=thread_id, message=unique_id,
        site=settings.INBOUND_EMAIL_DOMAIN)
    headers = {
        'In-Reply-To': reference_header,
        'References': reference_header,
        'Message-ID': message_id,
    }

    for recipient in recipients:
        token, created = ActivityLogToken.objects.get_or_create(
            version=version, user=recipient)
        if not created:
            token.update(use_count=0)
        else:
            log.info('Created token with UUID %s for user: %s.' % (
                token.uuid, recipient.id))
        reply_to = "%s%s@%s" % (
            REPLY_TO_PREFIX, token.uuid.hex, settings.INBOUND_EMAIL_DOMAIN)
        log.info('Sending activity email to %s for %s version %s' % (
            recipient, version.addon.pk, version.pk))
        send_mail(
            subject, message, recipient_list=[recipient.email],
            from_email=from_email, use_deny_list=False, headers=headers,
            perm_setting=perm_setting, reply_to=[reply_to])


NOT_PENDING_IDS = (
    amo.LOG.DEVELOPER_REPLY_VERSION.id,
    amo.LOG.APPROVE_VERSION.id,
    amo.LOG.REJECT_VERSION.id,
    amo.LOG.PRELIMINARY_VERSION.id,
    amo.LOG.PRELIMINARY_ADDON_MIGRATED.id,
    amo.LOG.APPROVAL_NOTES_CHANGED.id,
    amo.LOG.SOURCE_CODE_UPLOADED.id,
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
            render({'reason': reason, 'SITE_URL': settings.SITE_URL}))
    send_mail(
        'Re: %s' % message.get('Subject', 'your email to us'),
        body,
        recipient_list=[recipient['EmailAddress']],
        from_email=settings.REVIEWERS_EMAIL,
        use_deny_list=False)
