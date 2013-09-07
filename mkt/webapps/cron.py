import datetime
import os
import shutil
import stat
import time

from django.conf import settings
from django.db.models import Count

import commonware.log
import cronjobs
from celery.task.sets import TaskSet
from lib.es.utils import raise_if_reindex_in_progress
from lib.metrics import get_monolith_client

import amo
from amo.utils import chunked

import mkt

from .models import Installed, Webapp
from .tasks import webapp_update_weekly_downloads

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


def _get_trending(app_id, region=None):
    """
    Calculate trending.

    a = installs from 7 days ago to now
    b = installs from 28 days ago to 8 days ago, averaged per week

    trending = (a - b) / b if a > 100 and b > 1 else 0

    """
    client = get_monolith_client()

    kwargs = {'app-id': app_id}
    if region:
        kwargs['region'] = region.slug

    today = datetime.datetime.today()
    days_ago = lambda d: today - datetime.timedelta(days=d)

    # If we query monolith with interval=week and the past 7 days
    # crosses a Monday, Monolith splits the counts into two. We want
    # the sum over the past week so we need to `sum` these.
    count_1 = sum(
        c['count'] for c in
        client('app_installs', days_ago(7), today, 'week', **kwargs))

    # Get the average installs for the prior 3 weeks. Don't use the `len` of
    # the returned counts because of week boundaries.
    counts_3 = list(client('app_installs', days_ago(28), days_ago(8),
                           'week', **kwargs))
    count_3 = sum(c['count'] for c in counts_3) / 3

    if count_1 > 100 and count_3 > 1:
        return (count_1 - count_3) / count_3
    else:
        return 0.0


@cronjobs.register
def update_app_trending():
    """Update trending for all apps."""
    chunk_size = 300
    all_ids = list(Webapp.objects.values_list('id', flat=True))

    for ids in chunked(all_ids, chunk_size):
        apps = Webapp.objects.filter(id__in=ids).no_transforms()
        for app in apps:
            # Calculate global trending, then per-region trending below.
            value = _get_trending(app.id)
            if value:
                trending, created = app.trending.get_or_create(
                    region=0, defaults={'value': value})
                if not created:
                    trending.update(value=value)

            for region in mkt.regions.REGIONS_DICT.values():
                value = _get_trending(app.id, region)
                if value:
                    trending, created = app.trending.get_or_create(
                        region=region.id, defaults={'value': value})
                    if not created:
                        trending.update(value=value)

        # Let the database catch its breath.
        if len(all_ids) > chunk_size:
            time.sleep(10)
