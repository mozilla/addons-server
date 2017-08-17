import datetime

from django.core.management import call_command
from django.db.models import Sum, Max

import waffle
from celery.task.sets import TaskSet

import olympia.core.logger
from olympia.amo.utils import chunked
from .models import (
    AddonCollectionCount, CollectionCount, UpdateCount)
from . import tasks
from olympia.lib.es.utils import raise_if_reindex_in_progress

task_log = olympia.core.logger.getLogger('z.task')
cron_log = olympia.core.logger.getLogger('z.cron')


def update_addons_collections_downloads():
    """Update addons+collections download totals."""
    raise_if_reindex_in_progress('amo')

    d = (AddonCollectionCount.objects.values('addon', 'collection')
         .annotate(sum=Sum('count')))

    ts = [tasks.update_addons_collections_downloads.subtask(args=[chunk])
          for chunk in chunked(d, 100)]
    TaskSet(ts).apply_async()


def update_collections_total():
    """Update collections downloads totals."""

    d = (CollectionCount.objects.values('collection_id')
                                .annotate(sum=Sum('count')))

    ts = [tasks.update_collections_total.subtask(args=[chunk])
          for chunk in chunked(d, 50)]
    TaskSet(ts).apply_async()


def update_global_totals(date=None):
    """Update global statistics totals."""
    raise_if_reindex_in_progress('amo')

    if date:
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    # Assume that we want to populate yesterday's stats by default.
    today = date or datetime.date.today() - datetime.timedelta(days=1)
    today_jobs = [dict(job=job, date=today) for job in
                  tasks._get_daily_jobs(date)]

    max_update = date or UpdateCount.objects.aggregate(max=Max('date'))['max']
    metrics_jobs = [dict(job=job, date=max_update) for job in
                    tasks._get_metrics_jobs(date)]

    ts = [tasks.update_global_totals.subtask(kwargs=kw)
          for kw in today_jobs + metrics_jobs]
    TaskSet(ts).apply_async()


def update_google_analytics(date=None):
    """
    Update stats from Google Analytics.
    """
    if date:
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    else:
        # Assume that we want to populate yesterday's stats by default.
        date = datetime.date.today() - datetime.timedelta(days=1)
    tasks.update_google_analytics.delay(date=date)


def index_latest_stats(index=None):
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    def fmt(d):
        return d.strftime('%Y-%m-%d')

    raise_if_reindex_in_progress('amo')
    latest = UpdateCount.search(index).order_by('-date').values_dict('date')
    if latest:
        latest = latest[0]['date']
    else:
        latest = fmt(datetime.date.today() - datetime.timedelta(days=1))
    date_range = '%s:%s' % (latest, fmt(datetime.date.today()))
    cron_log.info('index_stats --date=%s' % date_range)
    call_command('index_stats', addons=None, date=date_range)
