from datetime import datetime, timedelta

from django.db import connection, connections, transaction
from django.db.models import Max, Q, F

import commonware.log
from celery.messaging import establish_connection
from celeryutils import task
import multidb

import amo
from amo.utils import chunked
import cronjobs

from .models import Addon

log = commonware.log.getLogger('z.cron')
task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def fast_current_version():
    # Only find the really recent versions; this is called a lot.
    t = datetime.now() - timedelta(minutes=5)
    qs = Addon.objects.no_cache().values_list('id')
    q1 = qs.filter(status=amo.STATUS_PUBLIC,
                   versions__files__datestatuschanged__gte=t)
    q2 = qs.filter(status__in=amo.UNREVIEWED_STATUSES,
                   versions__files__created__gte=t)
    addons = set(q1) | set(q2)
    if addons:
        _update_addons_current_version(addons)


#TODO(davedash): This will not be needed as a cron task after remora.
@cronjobs.register
def update_addons_current_version():
    """Update the current_version field of the addons."""
    d = (Addon.objects.filter(inactive=False, status__in=amo.VALID_STATUSES)
         .exclude(type=amo.ADDON_PERSONA).values_list('id'))

    with establish_connection() as conn:
        for chunk in chunked(d, 100):
            _update_addons_current_version.apply_async(args=[chunk],
                                                       connection=conn)


@task(rate_limit='20/m')
def _update_addons_current_version(data, **kw):
    task_log.info("[%s@%s] Updating addons current_versions." %
                   (len(data), _update_addons_current_version.rate_limit))
    for pk in data:
        try:
            addon = Addon.objects.get(pk=pk[0])
            addon.update_current_version()
        except Addon.DoesNotExist:
            task_log.debug("Missing addon: %d" % pk)
    transaction.commit_unless_managed()


@cronjobs.register
def update_addon_average_daily_users():
    """Update add-ons ADU totals."""
    cursor = connections[multidb.get_slave()].cursor()
    # We need to use SQL for this until
    # http://code.djangoproject.com/ticket/11003 is resolved
    q = """SELECT
               addon_id, AVG(`count`)
           FROM update_counts
           USE KEY (`addon_and_count`)
           GROUP BY addon_id
           ORDER BY addon_id"""
    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_addon_average_daily_users.apply_async(args=[chunk],
                                                          connection=conn)


@task(rate_limit='15/m')
def _update_addon_average_daily_users(data, **kw):
    task_log.info("[%s@%s] Updating add-ons ADU totals." %
                   (len(data), _update_addon_average_daily_users.rate_limit))

    for pk, count in data:
        Addon.objects.filter(pk=pk).update(average_daily_users=count)


@cronjobs.register
def update_addon_download_totals():
    """Update add-on total and average downloads."""
    cursor = connections[multidb.get_slave()].cursor()
    # We need to use SQL for this until
    # http://code.djangoproject.com/ticket/11003 is resolved
    q = """SELECT
               addon_id, AVG(count), SUM(count)
           FROM download_counts
           USE KEY (`addon_and_count`)
           GROUP BY addon_id
           ORDER BY addon_id"""
    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_addon_download_totals.apply_async(args=[chunk],
                                                      connection=conn)


@task(rate_limit='15/m')
def _update_addon_download_totals(data, **kw):
    task_log.info("[%s@%s] Updating add-ons download+average totals." %
                   (len(data), _update_addon_download_totals.rate_limit))

    for pk, avg, sum in data:
        Addon.objects.filter(pk=pk).update(average_daily_downloads=avg,
                                           total_downloads=sum)


def _change_last_updated(next):
    # We jump through some hoops here to make sure we only change the add-ons
    # that really need it, and to invalidate properly.
    current = dict(Addon.objects.values_list('id', 'last_updated'))
    changes = {}

    for addon, last_updated in next.items():
        if current[addon] != last_updated:
            changes[addon] = last_updated

    if not changes:
        return

    log.debug('Updating %s add-ons' % len(changes))
    # Update + invalidate.
    for addon in Addon.uncached.filter(id__in=changes).no_transforms():
        addon.last_updated = changes[addon.id]
        addon.save()


@cronjobs.register
def addon_last_updated():
    next = {}

    public = (Addon.uncached.filter(status=amo.STATUS_PUBLIC,
        versions__files__status=amo.STATUS_PUBLIC).values('id')
        .annotate(last_updated=Max('versions__files__datestatuschanged')))

    exp = (Addon.uncached.exclude(status=amo.STATUS_PUBLIC)
           .filter(versions__files__status__in=amo.VALID_STATUSES)
           .values('id')
           .annotate(last_updated=Max('versions__files__created')))

    listed = (Addon.uncached.filter(status=amo.STATUS_LISTED)
              .values('id')
              .annotate(last_updated=Max('versions__created')))

    personas = (Addon.uncached.filter(type=amo.ADDON_PERSONA)
                .extra(select={'last_updated': 'created'}))

    for q in (public, exp, listed, personas):
        for addon, last_updated in q.values_list('id', 'last_updated'):
            next[addon] = last_updated

    _change_last_updated(next)

    # Get anything that didn't match above.
    other = (Addon.uncached.filter(last_updated__isnull=True)
             .values_list('id', 'created'))
    _change_last_updated(dict(other))


@cronjobs.register
def update_addon_appsupport():
    # Find all the add-ons that need their app support details updated.
    newish = (Q(last_updated__gte=F('appsupport__created')) |
              Q(appsupport__created__isnull=True))
    # Search providers don't list supported apps.
    has_app = Q(versions__apps__isnull=False) | Q(type=amo.ADDON_SEARCH)
    good = (Q(has_app, versions__files__status__in=amo.VALID_STATUSES) |
            Q(type=amo.ADDON_PERSONA))
    ids = (Addon.objects.valid().no_cache().distinct()
           .filter(newish, good).values_list('id', flat=True))

    with establish_connection() as conn:
        for chunk in chunked(ids, 20):
            _update_appsupport.apply_async(args=[chunk], connection=conn)


@task(rate_limit='30/m')
@transaction.commit_manually
def _update_appsupport(ids, **kw):
    task_log.info("[%s@%s] Updating addons app_support." %
                   (len(ids), _update_appsupport.rate_limit))
    delete = 'DELETE FROM appsupport WHERE addon_id IN (%s)'
    insert = """INSERT INTO appsupport (addon_id, app_id, created, modified)
                VALUES %s"""

    addons = Addon.uncached.filter(id__in=ids).no_transforms()
    apps = [(addon.id, app.id) for addon in addons
            for app in addon.compatible_apps]
    s = ','.join('(%s, %s, NOW(), NOW())' % x for x in apps)

    if not apps:
        return

    cursor = connection.cursor()
    cursor.execute(delete % ','.join(map(str, ids)))
    cursor.execute(insert % s)
    transaction.commit()

    # All our updates were sql, so invalidate manually.
    Addon.objects.invalidate(*addons)
