import olympia.core.logger

from olympia.activity.models import ActivityLog, ActivityLogEmails, RatingLog
from olympia.activity.utils import add_email_to_activity_log_wrapper
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.ratings.models import Rating


log = olympia.core.logger.getLogger('z.amo.activity')


@task
@use_primary_db
def process_email(message, spam_rating, **kwargs):
    """Parse emails and save activity log entry."""
    # Some emails (gmail, at least) come with Message-ID instead of MessageId.
    msg_id = message.get('MessageId')
    if not msg_id:
        custom_headers = message.get('CustomHeaders', [])
        for header in custom_headers:
            if header.get('Name', '').lower() == 'message-id':
                msg_id = header.get('Value')
    if not msg_id:
        log.warning(
            'No MessageId in message, aborting.', extra={'message_obj': message}
        )
        return
    _, created = ActivityLogEmails.objects.get_or_create(messageid=msg_id)
    if not created:
        log.warning(
            'Already processed email [%s], skipping',
            msg_id,
            extra={'message_obj': message},
        )
        return
    res = add_email_to_activity_log_wrapper(message, spam_rating)

    if not res:
        log.warning(
            'Failed to process email [%s].', msg_id, extra={'message_obj': message}
        )


@task
def create_ratinglog(activitylog_ids):
    log.info(
        'Creating RatingLog for activities %d-%d [%d]',
        activitylog_ids[0],
        activitylog_ids[-1],
        len(activitylog_ids)
    )

    alogs = ActivityLog.objects.filter(id__in=activitylog_ids)
    for alog in alogs:
        rating = None
        for obj in alog.arguments:
            if isinstance(obj, Rating):
                rating = obj
                break
        else:
            log.info('No Rating to create a RatingLog for in ActivityLog %s', alog.pk)
            continue
        RatingLog.objects.get_or_create(activity_log=alog, rating=rating)
