import datetime
import itertools

from django.db import connection
from django.db.models import Max, Sum

from elasticsearch.helpers import bulk as bulk_index

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo import search as amo_search
from olympia.amo.celery import task
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import Version

from . import search
from .models import (
    AddonCollectionCount, CollectionCount, CollectionStats, DownloadCount,
    ThemeUserCount, UpdateCount)


log = olympia.core.logger.getLogger('z.task')


@task
def update_addons_collections_downloads(data, **kw):
    log.info("[%s] Updating addons+collections download totals." %
             (len(data)))
    query = (
        "UPDATE addons_collections SET downloads=%s WHERE addon_id=%s "
        "AND collection_id=%s;" * len(data))

    with connection.cursor() as cursor:
        cursor.execute(
            query,
            list(itertools.chain.from_iterable(
                [var['sum'], var['addon'], var['collection']]
                for var in data)))


@task
def update_collections_total(data, **kw):
    log.info("[%s] Updating collections' download totals." %
             (len(data)))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))


@task
def update_global_totals(job, date, **kw):
    log.info('Updating global statistics totals (%s) for (%s)' % (job, date))

    if isinstance(date, basestring):
        # Because of celery serialization, date is not date object, it has been
        # transformed into a string, we need the date object back.
        date = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S').date()

    jobs = _get_daily_jobs(date)
    jobs.update(_get_metrics_jobs(date))

    num = jobs[job]()

    q = """REPLACE INTO global_stats (`name`, `count`, `date`)
           VALUES (%s, %s, %s)"""
    p = [job, num or 0, date]

    try:
        cursor = connection.cursor()
        cursor.execute(q, p)
    except Exception, e:
        log.critical('Failed to update global stats: (%s): %s' % (p, e))
    else:
        log.debug('Committed global stats details: (%s) has (%s) for (%s)'
                  % tuple(p))
    finally:
        cursor.close()


def _get_daily_jobs(date=None):
    """Return a dictionary of statistics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to the previous day.
    """
    if not date:
        date = datetime.date.today() - datetime.timedelta(days=1)

    # Passing through a datetime would not generate an error,
    # but would pass and give incorrect values.
    if isinstance(date, datetime.datetime):
        raise ValueError('This requires a valid date object, not a datetime')

    # Testing on lte created date doesn't get you todays date, you need to do
    # less than next date. That's because 2012-1-1 becomes 2012-1-1 00:00
    next_date = date + datetime.timedelta(days=1)

    date_str = date.strftime('%Y-%m-%d')
    extra = {'where': ['DATE(created)=%s'], 'params': [date_str]}

    # If you're editing these, note that you are returning a function!  This
    # cheesy hackery was done so that we could pass the queries to celery
    # lazily and not hammer the db with a ton of these all at once.
    stats = {
        # Add-on Downloads
        'addon_total_downloads': lambda: DownloadCount.objects.filter(
            date__lt=next_date).aggregate(sum=Sum('count'))['sum'],
        'addon_downloads_new': lambda: DownloadCount.objects.filter(
            date=date).aggregate(sum=Sum('count'))['sum'],

        # Listed Add-on counts
        'addon_count_new': Addon.objects.valid().extra(**extra).count,

        # Listed Version counts
        'version_count_new': Version.objects.filter(
            channel=amo.RELEASE_CHANNEL_LISTED).extra(**extra).count,

        # User counts
        'user_count_total': UserProfile.objects.filter(
            created__lt=next_date).count,
        'user_count_new': UserProfile.objects.extra(**extra).count,

        # Rating counts
        'review_count_total': Rating.objects.filter(created__lte=date,
                                                    editorreview=0).count,
        # We can't use "**extra" here, because this query joins on reviews
        # itself, and thus raises the following error:
        # "Column 'created' in where clause is ambiguous".
        'review_count_new': Rating.objects.filter(editorreview=0).extra(
            where=['DATE(reviews.created)=%s'], params=[date_str]).count,

        # Collection counts
        'collection_count_total': Collection.objects.filter(
            created__lt=next_date).count,
        'collection_count_new': Collection.objects.extra(**extra).count,

        'collection_addon_downloads': (
            lambda: AddonCollectionCount.objects.filter(
                date__lte=date).aggregate(sum=Sum('count'))['sum']),
    }

    # If we're processing today's stats, we'll do some extras.  We don't do
    # these for re-processed stats because they change over time (eg. add-ons
    # move from sandbox -> public
    if date == (datetime.date.today() - datetime.timedelta(days=1)):
        stats.update({
            'addon_count_nominated': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_NOMINATED,
                disabled_by_user=0).count,
            'addon_count_public': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_PUBLIC,
                disabled_by_user=0).count,
            'addon_count_pending': Version.objects.filter(
                created__lte=date, files__status=amo.STATUS_PENDING).count,

            'collection_count_private': Collection.objects.filter(
                created__lte=date, listed=0).count,
            'collection_count_public': Collection.objects.filter(
                created__lte=date, listed=1).count,
            'collection_count_editorspicks': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_FEATURED).count,
            'collection_count_normal': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_NORMAL).count,
        })

    return stats


def _get_metrics_jobs(date=None):
    """Return a dictionary of statistics queries.

    If a date is specified and applies to the job it will be used.  Otherwise
    the date will default to the last date metrics put something in the db.
    """

    if not date:
        date = UpdateCount.objects.aggregate(max=Max('date'))['max']

    # If you're editing these, note that you are returning a function!
    stats = {
        'addon_total_updatepings': lambda: UpdateCount.objects.filter(
            date=date).aggregate(sum=Sum('count'))['sum'],
    }

    return stats


@task
def index_update_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = UpdateCount.objects.filter(id__in=ids)
    if qs.exists():
        log.info('Indexing %s updates for %s.' % (qs.count(), qs[0].date))
    data = []
    try:
        for update in qs:
            data.append(search.extract_update_count(update))
        bulk_index(es, data, index=index,
                   doc_type=UpdateCount.get_mapping_type(), refresh=True)
    except Exception, exc:
        index_update_counts.retry(args=[ids, index], exc=exc, **kw)
        raise


@task
def index_download_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = DownloadCount.objects.filter(id__in=ids)

    if qs.exists():
        log.info('Indexing %s downloads for %s.' % (qs.count(), qs[0].date))
    try:
        data = []
        for dl in qs:
            data.append(search.extract_download_count(dl))
        bulk_index(es, data, index=index,
                   doc_type=DownloadCount.get_mapping_type(), refresh=True)
    except Exception, exc:
        index_download_counts.retry(args=[ids, index], exc=exc)
        raise


@task
def index_collection_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = CollectionCount.objects.filter(collection__in=ids)

    if qs.exists():
        log.info('Indexing %s addon collection counts: %s'
                 % (qs.count(), qs[0].date))

    data = []
    try:
        for collection_count in qs:
            collection = collection_count.collection_id
            filters = dict(collection=collection,
                           date=collection_count.date)
            data.append(search.extract_addon_collection(
                collection_count,
                AddonCollectionCount.objects.filter(**filters),
                CollectionStats.objects.filter(**filters)))
        bulk_index(es, data, index=index,
                   doc_type=CollectionCount.get_mapping_type(),
                   refresh=True)
    except Exception, exc:
        index_collection_counts.retry(args=[ids], exc=exc)
        raise


@task
def index_theme_user_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = ThemeUserCount.objects.filter(id__in=ids)

    if qs.exists():
        log.info('Indexing %s theme user counts for %s.'
                 % (qs.count(), qs[0].date))
    data = []

    try:
        for user_count in qs:
            data.append(search.extract_theme_user_count(user_count))
        bulk_index(es, data, index=index,
                   doc_type=ThemeUserCount.get_mapping_type(), refresh=True)
    except Exception, exc:
        index_theme_user_counts.retry(args=[ids], exc=exc, **kw)
        raise
