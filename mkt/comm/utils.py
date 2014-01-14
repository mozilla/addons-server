from email import message_from_string
from email.utils import parseaddr

from django.core.exceptions import PermissionDenied

import commonware.log
from email_reply_parser import EmailReplyParser
import waffle

from access.models import Group
from users.models import UserProfile

from mkt.comm.models import (CommunicationNote, CommunicationNoteRead,
                             CommunicationThread, CommunicationThreadToken,
                             user_has_perm_thread)
from mkt.constants import comm


log = commonware.log.getLogger('comm')


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

    if (user_has_perm_thread(tok.thread, tok.user) and tok.is_valid()):
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


def create_comm_note(app, version, author, body, note_type=comm.NO_ACTION,
                     perms=None):
    """
    Creates a note on an app version's thread.
    Creates a thread if a thread doesn't already exist.
    CC's app's Mozilla contacts to auto-join thread.

    app -- app object.
    version -- app version.
    author -- UserProfile for the note's author.
    body -- string/text for note comment.
    note_type -- integer for note_type (mkt constant), defaults to 0/NO_ACTION
                 (e.g. comm.APPROVAL, comm.REJECTION, comm.NO_ACTION).
    perms -- object of groups to grant permission to, will set flags on Thread.
             (e.g. {'developer': False, 'staff': True}).

    """
    if not waffle.switch_is_active('comm-dashboard'):
        return None, None

    # Dict of {'read_permission_GROUP_TYPE': boolean}.
    # Perm for dev, reviewer, senior_reviewer, moz_contact, staff all True by
    # default.
    perms = perms or {}
    create_perms = dict(('read_permission_%s' % key, has_perm)
                        for key, has_perm in perms.iteritems())

    # Get or create thread w/ custom permissions.
    thread = None
    threads = app.threads.filter(version=version)
    if threads.exists():
        thread = threads[0]
    else:
        # See if user has perms to create thread for this app.
        thread = CommunicationThread(addon=app, version=version,
                                     **create_perms)
        if user_has_perm_thread(thread, author):
            thread.save()
        else:
            raise PermissionDenied

    # Create note.
    note = thread.notes.create(note_type=note_type, body=body, author=author,
                               **create_perms)

    post_create_comm_note(note)

    return thread, note


def post_create_comm_note(note):
    """Stuff to do after creating note, also used in comm api's post_save."""
    from mkt.reviewers.utils import send_note_emails

    thread = note.thread
    app = thread.addon

    # CC mozilla contact.
    for email in app.get_mozilla_contacts():
        try:
            moz_contact = UserProfile.objects.get(email=email)
            thread.thread_cc.get_or_create(user=moz_contact)
        except UserProfile.DoesNotExist:
            pass

    # CC note author, mark their own note as read.
    author = note.author
    cc, created_cc = thread.thread_cc.get_or_create(user=author)
    if not created_cc:
        note.mark_read(note.author)

    # Email.
    send_note_emails(note)
