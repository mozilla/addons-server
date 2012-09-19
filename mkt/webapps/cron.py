from datetime import datetime, timedelta
import os
import shutil
import stat
import time

from django.conf import settings
from django.db.models import Count

import commonware.log
import cronjobs
from celery.task.sets import TaskSet

import amo
from amo.utils import chunked

from .models import Installed
from .tasks import webapp_update_weekly_downloads

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def update_weekly_downloads():
    """Update the weekly "downloads" from the users_install table."""
    interval = datetime.today() - timedelta(days=7)
    counts = (Installed.objects.values('addon')
                               .filter(created__gte=interval,
                                       addon__type=amo.ADDON_WEBAPP)
                               .annotate(count=Count('addon')))

    ts = [webapp_update_weekly_downloads.subtask(args=[chunk])
          for chunk in chunked(counts, 1000)]
    TaskSet(ts).apply_async()


@cronjobs.register
def clean_old_signed(seconds=60 * 60):
    """Clean out apps signed for reviewers."""
    log.info('Removing old apps signed for reviewers')
    root = settings.SIGNED_APPS_REVIEWER_PATH
    for path in os.listdir(root):
        full = os.path.join(root, path)
        age = time.time() - os.stat(full)[stat.ST_ATIME]
        if age > seconds:
            log.debug('Removing signed app: %s, %dsecs old.' % (full, age))
            shutil.rmtree(full)
