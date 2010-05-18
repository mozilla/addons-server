import datetime
import logging

from django.db import connection, transaction
from django.db.models import Max, Sum

from celery.decorators import task
from celery.messaging import establish_connection

from .models import (AddonCollectionCount, CollectionCount,
                     DownloadCount, UpdateCount)
from addons.models import Addon
import amo
from amo.utils import chunked
from bandwagon.models import Collection, CollectionAddon
import cronjobs
from reviews.models import Review
from versions.models import Version
from users.models import UserProfile

task_log = logging.getLogger('z.task')


@cronjobs.register
def update_addons_collections_downloads():
    """Update addons+collections download totals."""

    d = (AddonCollectionCount.objects.values('addon', 'collection')
         .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 600):
            _update_addons_collections_downloads.apply_async(args=[chunk],
                                                             connection=conn)


@task(rate_limit='10/m')
def _update_addons_collections_downloads(data, **kw):
    task_log.debug("[%s@%s] Updating addons+collections download totals." %
                  (len(data), _update_addons_collections_downloads.rate_limit))
    for var in data:
        (CollectionAddon.objects.filter(addon=var['addon'],
                                        collection=var['collection'])
                                .update(downloads=var['sum']))


@cronjobs.register
def update_collections_total():
    """Update collections downloads totals."""

    d = (CollectionCount.objects.values('collection_id')
                                .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_collections_total.apply_async(args=[chunk],
                                                  connection=conn)


@task(rate_limit='15/m')
def _update_collections_total(data, **kw):
    task_log.debug("[%s@%s] Updating collections' download totals." %
                   (len(data), _update_collections_total.rate_limit))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))


@cronjobs.register
def update_global_totals():
    """Update global statistics totals."""

    today = datetime.date.today()
    today_jobs = [dict(job=job, date=today) for job in _get_daily_jobs()]

    max_update = UpdateCount.objects.aggregate(max=Max('date'))['max']
    metrics_jobs = [dict(job=job, date=max_update) for job in _get_metrics_jobs()]

    with establish_connection() as conn:
        for kw in today_jobs + metrics_jobs:
            _update_global_totals.apply_async(kwargs=kw,
                                              connection=conn)


@task(rate_limit='20/h')
def _update_global_totals(job, date):
    task_log.debug("[%s] Updating global statistics totals (%s) for (%s)" %
                   (_update_global_totals.rate_limit, job, date))

    jobs = _get_daily_jobs()
    jobs.update(_get_metrics_jobs())

    num = jobs[job]()

    q = """REPLACE INTO
                global_stats(`name`, `count`, `date`)
            VALUES
                (%s, %s, %s)"""
    p = [job, num or 0, date]

    cursor = connection.cursor()
    cursor.execute(q, p)
    transaction.commit_unless_managed()


def _get_daily_jobs(date=None):
    """Return a dictionary of statisitics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to today().
    """

    if not date:
        date = datetime.date.today()

    extra = dict(where=['DATE(created)=%s'], params=[date])

    # If you're editing these, note that you are returning a function!  This
    # cheesy hackery was done so that we could pass the queries to celery lazily
    # and not hammer the db with a ton of these all at once.
    stats = {
        # Add-on Downloads
        'addon_total_downloads': lambda: DownloadCount.objects.aggregate(sum=Sum('count'))['sum'],
        'addon_downloads_new': lambda: DownloadCount.objects.filter(date=date).aggregate(sum=Sum('count'))['sum'],

        # Add-on counts
        'addon_count_public': Addon.objects.filter(status=amo.STATUS_PUBLIC, inactive=0).count,
        'addon_count_pending': Version.objects.filter(files__status=amo.STATUS_PENDING).count,
        'addon_count_experimental': Addon.objects.filter(status=amo.STATUS_UNREVIEWED, inactive=0).count,
        'addon_count_nominated': Addon.objects.filter(status=amo.STATUS_NOMINATED, inactive=0).count,
        'addon_count_new': Addon.objects.extra(**extra).count,

        # Version counts
        'version_count_new': Version.objects.extra(**extra).count,

        # User counts
        'user_count_total': UserProfile.objects.count,
        'user_count_new': UserProfile.objects.extra(**extra).count,

        # Review counts
        'review_count_total': Review.objects.filter(editorreview=0).count,
        'review_count_new': Review.objects.filter(editorreview=0).extra(**extra).count,

        # Collection counts
        'collection_count_total': Collection.objects.count,
        'collection_count_new': Collection.objects.extra(**extra).count,
        'collection_count_private': Collection.objects.filter(listed=0).count,
        'collection_count_public': Collection.objects.filter(listed=1).count,
        'collection_count_autopublishers': Collection.objects.filter(type=amo.COLLECTION_SYNCHRONIZED).count,
        'collection_count_editorspicks': Collection.objects.filter(type=amo.COLLECTION_FEATURED).count,
        'collection_count_normal': Collection.objects.filter(type=amo.COLLECTION_NORMAL).count,

        'collection_addon_downloads': lambda: AddonCollectionCount.objects.aggregate(sum=Sum('count'))['sum'],
    }

    return stats


def _get_metrics_jobs(date=None):
    """Return a dictionary of statisitics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to the last date metrics put something in the db.
    """

    if not date:
        date = UpdateCount.objects.aggregate(max=Max('date'))['max']

    # If you're editing these, note that you are returning a function!
    stats = {
        'addon_total_updatepings': lambda: UpdateCount.objects.filter(date=date).aggregate(sum=Sum('count'))['sum'],
        'collector_updatepings': lambda: UpdateCount.objects.get(addon=11950, date=date).count,
    }

    return stats
