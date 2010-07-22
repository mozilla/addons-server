import datetime

from django.db import connection, transaction
from django.db.models import Sum, Max

import commonware.log
from celery.decorators import task

import amo
from addons.models import Addon
from bandwagon.models import Collection, CollectionAddon
from stats.models import Contribution
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version
from .models import UpdateCount, DownloadCount, AddonCollectionCount

log = commonware.log.getLogger('z.task')


@task
def addon_total_contributions(*addons):
    "Updates the total contributions for a given addon."

    log.info('[%s@%s] Updating total contributions.' %
             (len(addons), addon_total_contributions.rate_limit))
    # Only count uuid=None; those are verified transactions.
    stats = (Contribution.objects.filter(addon__in=addons, uuid=None)
             .values_list('addon').annotate(Sum('amount')))

    for addon, total in stats:
        Addon.objects.filter(id=addon).update(total_contributions=total)


@task(rate_limit='10/m')
def cron_total_contributions(*addons):
    "Rate limited version of `addon_total_contributions` suitable for cron."
    addon_total_contributions(*addons)


@task(rate_limit='10/m')
def update_addons_collections_downloads(data, **kw):
    log.info("[%s@%s] Updating addons+collections download totals." %
                  (len(data), update_addons_collections_downloads.rate_limit))
    for var in data:
        (CollectionAddon.objects.filter(addon=var['addon'],
                                        collection=var['collection'])
                                .update(downloads=var['sum']))


@task(rate_limit='15/m')
def update_collections_total(data, **kw):
    log.info("[%s@%s] Updating collections' download totals." %
                   (len(data), update_collections_total.rate_limit))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))


@task(rate_limit='20/h')
def update_global_totals(job, date):
    log.info("[%s] Updating global statistics totals (%s) for (%s)" %
                   (update_global_totals.rate_limit, job, date))

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
    # cheesy hackery was done so that we could pass the queries to celery
    # lazily and not hammer the db with a ton of these all at once.
    stats = {
        # Add-on Downloads
        'addon_total_downloads': lambda: DownloadCount.objects.filter(
                date__lte=date).aggregate(sum=Sum('count'))['sum'],
        'addon_downloads_new': lambda: DownloadCount.objects.filter(
                date=date).aggregate(sum=Sum('count'))['sum'],

        # Add-on counts
        'addon_count_public': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_PUBLIC, inactive=0).count,
        'addon_count_pending': Version.objects.filter(
                created__lte=date, files__status=amo.STATUS_PENDING).count,
        'addon_count_experimental': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_UNREVIEWED,
                inactive=0).count,
        'addon_count_nominated': Addon.objects.filter(
                created__lte=date, status=amo.STATUS_NOMINATED,
                inactive=0).count,
        'addon_count_new': Addon.objects.extra(**extra).count,

        # Version counts
        'version_count_new': Version.objects.extra(**extra).count,

        # User counts
        'user_count_total': UserProfile.objects.filter(
                created__lte=date).count,
        'user_count_new': UserProfile.objects.extra(**extra).count,

        # Review counts
        'review_count_total': Review.objects.filter(created__lte=date,
                                                    editorreview=0).count,
        'review_count_new': Review.objects.filter(editorreview=0).extra(
                **extra).count,

        # Collection counts
        'collection_count_total': Collection.objects.filter(
                created__lte=date).count,
        'collection_count_new': Collection.objects.extra(**extra).count,
        'collection_count_private': Collection.objects.filter(listed=0).count,
        'collection_count_public': Collection.objects.filter(
                created__lte=date, listed=1).count,
        'collection_count_autopublishers': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_SYNCHRONIZED).count,
        'collection_count_editorspicks': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_FEATURED).count,
        'collection_count_normal': Collection.objects.filter(
                created__lte=date, type=amo.COLLECTION_NORMAL).count,

        'collection_addon_downloads': (lambda:
            AddonCollectionCount.objects.filter(date__lte=date).aggregate(
                sum=Sum('count'))['sum']),
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
        'addon_total_updatepings': lambda: UpdateCount.objects.filter(
                date=date).aggregate(sum=Sum('count'))['sum'],
        'collector_updatepings': lambda: UpdateCount.objects.get(
                addon=11950, date=date).count,
    }

    return stats
