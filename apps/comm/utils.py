from email import message_from_string
from email.utils import parseaddr

import commonware.log
from email_reply_parser import EmailReplyParser

from access import acl
from comm.models import (CommunicationNote, CommunicationNoteRead,
                         CommunicationThreadCC, CommunicationThreadToken)
from mkt.constants import comm


log = commonware.log.getLogger('comm')


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

    address_prefix = 'reply+'

    def __init__(self, email_text):
        self.email = message_from_string(email_text)
        self.reply_text = EmailReplyParser.read(self.email.get_payload()).reply

    def _get_address_line(self):
        return parseaddr(self.email['to'])

    def get_uuid(self):
        name, addr = self._get_address_line()
        if addr.startswith(self.address_prefix):
            # Strip everything between "reply+" and the "@" sign.
            uuid = addr.lstrip(self.address_prefix).split('@')[0]
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

    if ThreadObjectPermission().user_has_permission(tok.thread, tok.user):
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
        return queryset.exclude(pk__in=notes) if notes else queryset
