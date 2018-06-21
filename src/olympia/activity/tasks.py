import olympia.core.logger

from olympia.activity.models import ActivityLogEmails
from olympia.activity.utils import add_email_to_activity_log_wrapper
from olympia.amo.celery import task
from olympia.amo.decorators import write


@task
@write
def process_email(message, **kwargs):
    """Parse emails and save activity log entry."""
    # Some emails (gmail, at least) come with Message-ID instead of MessageId.
    msg_id = message.get('MessageId')
    if not msg_id:
        custom_headers = message.get('CustomHeaders', [])
        for header in custom_headers:
            if header.get('Name', '').lower() == 'message-id':
                msg_id = header.get('Value')
    if not msg_id:
        log.error('No MessageId in message, aborting.')
        log.error(message)
        return
    _, created = ActivityLogEmails.objects.get_or_create(messageid=msg_id)
    if not created:
        log.error('Already processed [%s], skipping' % msg_id)
        log.error(message)
        return
    res = add_email_to_activity_log_wrapper(message)

    if not res:
        log.error('Failed to save email.')
