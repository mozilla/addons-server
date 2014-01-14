from django.core.management.base import BaseCommand

import commonware.log
from celeryutils import task

import amo
from amo.decorators import write
from amo.utils import chunked
from devhub.models import ActivityLog, AppLog

from mkt.comm.models import CommunicationNote, CommunicationThread
import mkt.constants.comm as cmb


log = commonware.log.getLogger('comm')


class Command(BaseCommand):
    help = ('Migrates ActivityLog objects to CommunicationNote objects. '
            'Meant for one time run only.')

    def handle(self, *args, **options):
        activity_ids = AppLog.objects.values_list('activity_log', flat=True)
        logs = (ActivityLog.objects.filter(
            pk__in=list(activity_ids), action__in=amo.LOG_REVIEW_QUEUE)
            .order_by('created'))

        for log_chunk in chunked(logs, 100):
            _migrate_activity_log.delay(log_chunk)


@task
@write
def _migrate_activity_log(logs, **kwargs):
    """For migrate_activity_log.py script."""
    for log in logs:
        action = cmb.ACTION_MAP(log.action)

        # Create thread.
        thread, tc = CommunicationThread.objects.safer_get_or_create(
            addon=log.arguments[0], version=log.arguments[1])

        # Filter notes.
        note_params = {
            'thread': thread,
            'note_type': action,
            'author': log.user,
            'body': log.details.get('comments', '') if log.details else '',
        }
        notes = CommunicationNote.objects.filter(created=log.created,
                                                 **note_params)
        if notes.exists():
            # Note already exists, move on.
            continue

        # Create note.
        note = CommunicationNote.objects.create(
            # Developers should not see escalate/reviewer comments.
            read_permission_developer=action not in (cmb.ESCALATION,
                                                     cmb.REVIEWER_COMMENT),
            **note_params)
        note.update(created=log.created)

        # Attachments.
        if note.attachments.exists():
            # Already migrated. Continue.
            continue

        # Create attachments.
        for attachment in log.activitylogattachment_set.all():
            note_attachment = note.attachments.create(
                filepath=attachment.filepath, mimetype=attachment.mimetype,
                description=attachment.description)
            note_attachment.update(created=attachment.created)
