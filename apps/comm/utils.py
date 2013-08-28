from email import message_from_string
from email.utils import parseaddr

import commonware.log
from email_reply_parser import EmailReplyParser
import waffle

from access import acl
from access.models import Group
from comm.models import (CommunicationNote, CommunicationNoteRead,
                         CommunicationThreadCC, CommunicationThread,
                         CommunicationThreadToken)
from mkt.constants import comm
from users.models import UserProfile


log = commonware.log.getLogger('comm')
action_note_types = {
    'approve': comm.APPROVAL,
    'disable': comm.DISABLED,
    'escalate': comm.ESCALATION,
    'info': comm.MORE_INFO_REQUIRED,
    'comment': comm.REVIEWER_COMMENT,
    'reject': comm.REJECTION,
    'resubmit': comm.RESUBMISSION
}


class ThreadObjectPermission(object):
    """
    Class for determining user permissions on a thread.
    """

    def check_acls(self, acl_type):
        """Check ACLs."""
        user = self.user_profile
        obj = self.thread_obj
        if acl_type == 'moz_contact':
            return user.email in obj.addon.get_mozilla_contacts()
        elif acl_type == 'admin':
            return acl.action_allowed_user(user, 'Admin', '%')
        elif acl_type == 'reviewer':
            return acl.action_allowed_user(user, 'Apps', 'Review')
        elif acl_type == 'senior_reviewer':
            return acl.action_allowed_user(user, 'Apps', 'ReviewEscalated')
        else:
            raise 'Invalid ACL lookup.'

        return False

    def user_has_permission(self, thread, profile):
        """
        Check if the user has read/write permissions on the given thread.

        Developers of the add-on used in the thread, users in the CC list,
        and users who post to the thread are allowed to access the object.

        Moreover, other object permissions are also checked agaisnt the ACLs
        of the user.
        """
        self.thread_obj = thread
        self.user_profile = profile
        user_post = CommunicationNote.objects.filter(author=profile,
            thread=thread)
        user_cc = CommunicationThreadCC.objects.filter(user=profile,
            thread=thread)

        if user_post.exists() or user_cc.exists():
            return True

        # User is a developer of the add-on and has the permission to read.
        user_is_author = profile.addons.filter(pk=thread.addon_id)
        if thread.read_permission_developer and user_is_author.exists():
            return True

        if thread.read_permission_reviewer and self.check_acls('reviewer'):
            return True

        if (thread.read_permission_senior_reviewer and
            self.check_acls('senior_reviewer')):
            return True

        if (thread.read_permission_mozilla_contact and
            self.check_acls('moz_contact')):
            return True

        if thread.read_permission_staff and self.check_acls('admin'):
            return True

        return False


class CommEmailParser(object):
    """Utility to parse email replies."""

    address_prefix = comm.REPLY_TO_PREFIX

    def __init__(self, email_text):
        self.email = message_from_string(email_text)
        self.reply_text = EmailReplyParser.read(self.email.get_payload()).reply

    def _get_address_line(self):
        return parseaddr(self.email['to'])

    def get_uuid(self):
        name, addr = self._get_address_line()
        if addr.startswith(self.address_prefix):
            # Strip everything between "reply+" and the "@" sign.
            uuid = addr[len(self.address_prefix):].split('@')[0]
        else:
            return False

        return uuid

    def get_body(self):
        return self.reply_text


def save_from_email_reply(reply_text):
    parser = CommEmailParser(reply_text)
    uuid = parser.get_uuid()

    if not uuid:
        return False
    try:
        tok = CommunicationThreadToken.objects.get(uuid=uuid)
    except CommunicationThreadToken.DoesNotExist:
        log.error('An email was skipped with non-existing uuid %s' % uuid)
        return False

    if (ThreadObjectPermission().user_has_permission(tok.thread, tok.user) and
        tok.is_valid()):
        n = CommunicationNote.objects.create(note_type=comm.NO_ACTION,
            thread=tok.thread, author=tok.user, body=parser.get_body())
        log.info('A new note has been created (from %s using tokenid %s)' %
                 (tok.user.id, uuid))
        return n
    return False


def filter_notes_by_read_status(queryset, profile, read_status=True):
    """
    Filter read/unread notes using this method.

    `read_status` = `True` for read notes, `False` for unread notes.
    """
    # Get some read notes from db.
    notes = list(CommunicationNoteRead.objects.filter(
        user=profile).values_list('note', flat=True))

    if read_status:
        # Filter and return read notes if they exist.
        return queryset.filter(pk__in=notes) if notes else queryset.none()
    else:
        # Exclude read notes if they exist.
        return queryset.exclude(pk__in=notes) if notes else queryset.all()


def get_reply_token(thread, user_id):
    tok, created = CommunicationThreadToken.objects.get_or_create(
        thread=thread, user_id=user_id)

    # We expire a token after it has been used for a maximum number of times.
    # This is usually to prevent overusing a single token to spam to threads.
    # Since we're re-using tokens, we need to make sure they are valid for
    # replying to new notes so we reset their `use_count`.
    if not created:
        tok.update(use_count=0)
    else:
        log.info('Created token with UUID %s for user_id: %s.' %
                 (tok.uuid, user_id))
    return tok


def get_recipients(note, fresh_thread=False):
    """
    Create/refresh tokens for users based on the thread permissions.
    """
    thread = note.thread

    # TODO: Possible optimization.
    # Fetch tokens from the database if `fresh_thread=False` and use them to
    # derive the list of recipients instead of doing a couple of multi-table
    # DB queries.
    recipients = set(thread.thread_cc.values_list('user__id', 'user__email'))

    # Include devs.
    if note.read_permission_developer:
        recipients.update(thread.addon.authors.values_list('id', 'email'))

    groups_list = []
    # Include app reviewers.
    if note.read_permission_reviewer:
        groups_list.append('App Reviewers')

    # Include senior app reviewers.
    if note.read_permission_senior_reviewer:
        groups_list.append('Senior App Reviewers')

    # Include admins.
    if note.read_permission_staff:
        groups_list.append('Admins')

    if len(groups_list) > 0:
        groups = Group.objects.filter(name__in=groups_list)
        for group in groups:
            recipients.update(group.users.values_list('id', 'email'))

    # Include Mozilla contact.
    if (note.read_permission_mozilla_contact and
        thread.addon.mozilla_contact):
        for moz_contact in thread.addon.get_mozilla_contacts():
            try:
                user = UserProfile.objects.get(email=moz_contact)
            except UserProfile.DoesNotExist:
                pass
            else:
                recipients.add((user.id, moz_contact))

    if (note.author.id, note.author.email) in recipients:
        recipients.remove((note.author.id, note.author.email))

    new_recipients_list = []
    for user_id, user_email in recipients:
        tok = get_reply_token(note.thread, user_id)
        new_recipients_list.append((user_email, tok.uuid))

    return new_recipients_list


def create_comm_thread(**kwargs):
    if not waffle.switch_is_active('comm-dashboard'):
        return

    addon = kwargs['addon']
    version = kwargs['version']
    thread = CommunicationThread.objects.filter(addon=addon, version=version)

    perms = {}
    for key in kwargs['perms']:
        perms['read_permission_%s' % key] = True

    if thread.exists():
        thread = thread[0]
    else:
        thread = CommunicationThread.objects.create(addon=addon,
            version=version, **perms)

    note = CommunicationNote.objects.create(
        note_type=action_note_types[kwargs['action']],
        body=kwargs['comments'], author=kwargs['profile'],
        thread=thread, **perms)

    moz_emails = addon.get_mozilla_contacts()

    # CC mozilla contact.
    for email in moz_emails:
        try:
            moz_contact = UserProfile.objects.get(email=email)
        except UserProfile.DoesNotExist:
            pass
        else:
            CommunicationThreadCC.objects.get_or_create(
                thread=thread, user=moz_contact)
    return thread, note
