from datetime import datetime, timedelta
import os
import time

from django.conf import settings

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

    # Delete the dump apps over 30 days.
    for app in os.listdir(settings.DUMPED_APPS_PATH):
        app = os.path.join(settings.DUMPED_APPS_PATH, app)
        if (os.stat(app).st_mtime < time.time() -
            settings.DUMPED_APPS_DAYS_DELETE):
            log.debug('Deleting old tarball: {0}'.format(app))
            os.remove(app)

    # Delete the dumped user installs over 30 days.
    tarball_path = os.path.join(settings.DUMPED_USERS_PATH, 'tarballs')
    for filename in os.listdir(tarball_path):
        filepath = os.path.join(tarball_path, filename)
        if (os.stat(filepath).st_mtime < time.time() -
            settings.DUMPED_USERS_DAYS_DELETE):
            log.debug('Deleting old tarball: {0}'.format(filepath))
            os.remove(filepath)
