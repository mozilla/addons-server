from django.core.cache import cache

import commonware.log
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.activity.utils import add_email_to_activity_log_wrapper


log = commonware.log.getLogger('z.amo.activity')


@task
@write
def process_email(message, **kwargs):
    """Parse emails and save activity log entry."""
    msg_id = message.get('MessageId', None)
    if not msg_id:
        log.error('No MessageId in message, aborting.')
        return
    cache_key = 'process_email:%s' % msg_id
    if cache.get(cache_key):
        log.error('Already processed [%s] in the last 60s, skipping' % msg_id)
        return
    cache.set(cache_key, 'yes', 60)
    res = add_email_to_activity_log_wrapper(message)

    if not res:
        log.error('Failed to save email.')
