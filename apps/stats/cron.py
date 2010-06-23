import datetime

from django.db.models import Sum, Max

import commonware.log
from celery.messaging import establish_connection

import cronjobs
from amo.utils import chunked
from addons.models import Addon
from .models import (AddonCollectionCount, CollectionCount,
                     UpdateCount)
from . import tasks

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def update_addons_collections_downloads():
    """Update addons+collections download totals."""

    d = (AddonCollectionCount.objects.values('addon', 'collection')
         .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 600):
            tasks.update_addons_collections_downloads.apply_async(
                    args=[chunk], connection=conn)


@cronjobs.register
def update_collections_total():
    """Update collections downloads totals."""

    d = (CollectionCount.objects.values('collection_id')
                                .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            tasks.update_collections_total.apply_async(args=[chunk],
                                                       connection=conn)


@cronjobs.register
def update_global_totals(date=None):
    """Update global statistics totals."""

    today = date or datetime.date.today()
    today_jobs = [dict(job=job, date=today) for job in tasks._get_daily_jobs()]

    max_update = date or UpdateCount.objects.aggregate(max=Max('date'))['max']
    metrics_jobs = [dict(job=job, date=max_update) for job in
                    tasks._get_metrics_jobs()]

    with establish_connection() as conn:
        for kw in today_jobs + metrics_jobs:
            tasks.update_global_totals.apply_async(kwargs=kw, connection=conn)


@cronjobs.register
def addon_total_contributions():
    addons = Addon.objects.values_list('id', flat=True)
    with establish_connection() as conn:
        for chunk in chunked(addons, 100):
            tasks.cron_total_contributions.apply_async(args=chunk,
                                                       connection=conn)
