from datetime import datetime, timedelta

import commonware.log
import cronjobs

import amo
from amo.utils import chunked
from devhub.models import ActivityLog

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def mkt_gc(**kw):
    """Site-wide garbage collections."""

    days_ago = lambda days: datetime.today() - timedelta(days=days)

    log.debug('Collecting data to delete')
    logs = (ActivityLog.objects.filter(created__lt=days_ago(90))
            .exclude(action__in=amo.LOG_KEEP).values_list('id', flat=True))

    for chunk in chunked(logs, 100):
        chunk.sort()
        log.debug('Deleting log entries: %s' % str(chunk))
        amo.tasks.delete_logs.delay(chunk)
