import logging
from celeryutils import task

from mkt.comm.models import CommunicationNoteRead
from mkt.comm.utils import filter_notes_by_read_status, save_from_email_reply


log = logging.getLogger('z.task')


@task
def consume_email(email_text, **kwargs):
    """Parse emails and save notes."""
    res = save_from_email_reply(email_text)
    if not res:
        log.error('Failed to save email.')


@task
def mark_thread_read(thread, user, **kwargs):
    """This marks each unread note in a thread as read - in bulk."""
    object_list = []
    unread_notes = filter_notes_by_read_status(thread.notes, user, False)

    for note in unread_notes:
        object_list.append(CommunicationNoteRead(note=note, user=user))

    CommunicationNoteRead.objects.bulk_create(object_list)
