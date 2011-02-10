import os
from datetime import datetime, timedelta

from django.db import connections, transaction
from django.db.models import Q, F
from django.utils.encoding import smart_str

import commonware.log
from celery.messaging import establish_connection
from celeryutils import task
import multidb

import amo
import cronjobs
from amo.utils import chunked
from addons.models import Addon
from addons.utils import ReverseNameLookup
from files.models import File
from translations.models import Translation

log = commonware.log.getLogger('z.cron')
task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def build_reverse_name_lookup():
    """Builds a Reverse Name lookup table in REDIS."""

    # Get all add-on name ids
    names = (Addon.objects.filter(
        name__isnull=False, type__in=[amo.ADDON_EXTENSION, amo.ADDON_THEME])
        .values_list('name_id', 'id'))

    for chunk in chunked(names, 100):
        _build_reverse_name_lookup.delay(dict(chunk))


@task
def _build_reverse_name_lookup(names, **kw):
    clear = kw.get('clear', False)
    translations = (Translation.objects.filter(id__in=names)
                    .values_list('id', 'localized_string'))

    if clear:
        for addon_id in names.values():
            ReverseNameLookup.delete(addon_id)

    for t_id, string in translations:
        if string:
            ReverseNameLookup.add(string, names[t_id])


@cronjobs.register
def fast_current_version():
    # Only find the really recent versions; this is called a lot.
    t = datetime.now() - timedelta(minutes=5)
    qs = Addon.objects.values_list('id')
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
    d = (Addon.objects.filter(disabled_by_user=False,
                              status__in=amo.VALID_STATUSES)
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
    for q in Addon._last_updated_queries().values():
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
    has_file = (Q(status=amo.STATUS_LISTED) |
                Q(versions__files__status__in=amo.VALID_STATUSES))
    good = Q(has_app, has_file) | Q(type=amo.ADDON_PERSONA)
    ids = (Addon.objects.valid().no_cache().distinct()
           .filter(newish, good).values_list('id', flat=True))

    with establish_connection() as conn:
        for chunk in chunked(ids, 20):
            _update_appsupport.apply_async(args=[chunk], connection=conn)


@task(rate_limit='30/m')
@transaction.commit_manually
def _update_appsupport(ids, **kw):
    from .tasks import update_appsupport
    update_appsupport(ids)


@cronjobs.register
def addons_add_slugs():
    """Give slugs to any slugless addons."""
    Addon._meta.get_field('modified').auto_now = False
    q = Addon.objects.filter(slug=None).order_by('id')
    ids = q.values_list('id', flat=True)

    cnt = 0
    total = len(ids)
    task_log.info('%s addons without slugs' % total)
    # Chunk it so we don't do huge queries.
    for chunk in chunked(ids, 300):
        # Slugs are set in Addon.__init__.
        list(q.no_cache().filter(id__in=chunk))
        cnt += 300
        task_log.info('Slugs added to %s/%s add-ons.' % (cnt, total))


@cronjobs.register
def hide_disabled_files():
    # If an add-on or a file is disabled, it should be moved to
    # GUARDED_ADDONS_PATH so it's not publicly visible.
    q = (Q(version__addon__status=amo.STATUS_DISABLED)
         | Q(version__addon__disabled_by_user=True))
    ids = (File.objects.filter(q | Q(status=amo.STATUS_DISABLED))
           .values_list('id', flat=True))
    for chunk in chunked(ids, 300):
        qs = File.uncached.filter(id__in=chunk).select_related('version')
        for f in qs:
            f.hide_disabled_file()
