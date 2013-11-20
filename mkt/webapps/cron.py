import datetime
import os
import shutil
import stat
import time

from django.conf import settings
from django.db.models import Count

import commonware.log
import cronjobs
from celery import chord
from celery.task.sets import TaskSet
from lib.es.utils import raise_if_reindex_in_progress

import amo
from amo.utils import chunked

from .models import Installed, Webapp
from .tasks import (dump_user_installs, update_trending,
                    webapp_update_weekly_downloads, zip_users)

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def update_weekly_downloads():
    """Update the weekly "downloads" from the users_install table."""
    raise_if_reindex_in_progress()
    interval = datetime.datetime.today() - datetime.timedelta(days=7)
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


@cronjobs.register
def update_app_trending():
    """
    Update trending for all apps.

    Spread these tasks out successively by 15 seconds so they don't hit
    Monolith all at once.

    """
    chunk_size = 50
    seconds_between = 15

    all_ids = list(Webapp.objects.filter(status=amo.STATUS_PUBLIC)
                   .values_list('id', flat=True))

    countdown = 0
    for ids in chunked(all_ids, chunk_size):
        update_trending.delay(ids, countdown=countdown)
        countdown += seconds_between


@cronjobs.register
def dump_user_installs_cron():
    """
    Sets up tasks to do user install dumps.
    """
    chunk_size = 100
    # Get valid users to dump.
    user_ids = set(Installed.objects.filter(addon__type=amo.ADDON_WEBAPP)
                   .values_list('user', flat=True))

    # Remove old dump data before running.
    user_dir = os.path.join(settings.DUMPED_USERS_PATH, 'users')
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

    grouping = []
    for chunk in chunked(user_ids, chunk_size):
        grouping.append(dump_user_installs.subtask(args=[chunk]))

    post = zip_users.subtask(immutable=True)
    ts = chord(grouping, post)
    ts.apply_async()
