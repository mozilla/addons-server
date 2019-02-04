import os
import time

from datetime import datetime, timedelta

from django.conf import settings
from django.db import connections
from django.db.models import Avg, F, Q, Sum
from django.utils.encoding import force_text

import multidb
import waffle

from celery import group

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, AppSupport, FrozenAddon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import chunked, walkfiles
from olympia.files.models import File
from olympia.lib.es.utils import raise_if_reindex_in_progress
from olympia.stats.models import UpdateCount


log = olympia.core.logger.getLogger('z.cron')
task_log = olympia.core.logger.getLogger('z.task')


def update_addon_average_daily_users():
    """Update add-ons ADU totals."""
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    raise_if_reindex_in_progress('amo')
    cursor = connections[multidb.get_slave()].cursor()
    q = """SELECT addon_id, AVG(`count`)
           FROM update_counts
           WHERE `date` > DATE_SUB(CURDATE(), INTERVAL 13 DAY)
           GROUP BY addon_id
           ORDER BY addon_id"""
    cursor.execute(q)
    d = cursor.fetchall()
    cursor.close()

    ts = [_update_addon_average_daily_users.subtask(args=[chunk])
          for chunk in chunked(d, 250)]
    group(ts).apply_async()


@task
def _update_addon_average_daily_users(data, **kw):
    task_log.info("[%s] Updating add-ons ADU totals." % (len(data)))

    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    for pk, count in data:
        try:
            addon = Addon.objects.get(pk=pk)
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons
            m = "Got an ADU update (%s) but the add-on doesn't exist (%s)"
            task_log.debug(m % (count, pk))
            continue

        addon.update(average_daily_users=int(float(count)))


def update_addon_download_totals():
    """Update add-on total and average downloads."""
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    qs = (
        Addon.objects
             .annotate(sum_download_count=Sum('downloadcount__count'))
             .values_list('id', 'sum_download_count')
             .order_by('id')
    )
    ts = [_update_addon_download_totals.subtask(args=[chunk])
          for chunk in chunked(qs, 250)]
    group(ts).apply_async()


@task
def _update_addon_download_totals(data, **kw):
    task_log.info('[%s] Updating add-ons download+average totals.' %
                  (len(data)))

    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    for pk, sum_download_counts in data:
        try:
            addon = Addon.objects.get(pk=pk)
            # Don't trigger a save unless we have to (the counts may not have
            # changed)
            if (sum_download_counts and
                    addon.total_downloads != sum_download_counts):
                addon.update(total_downloads=sum_download_counts)
        except Addon.DoesNotExist:
            # We exclude deleted add-ons in the cron, but an add-on could have
            # been deleted by the time the task is processed.
            m = ("Got new download totals (total=%s) but the add-on"
                 "doesn't exist (%s)" % (sum_download_counts, pk))
            task_log.debug(m)


def _change_last_updated(next):
    # We jump through some hoops here to make sure we only change the add-ons
    # that really need it, and to invalidate properly.
    current = dict(Addon.objects.values_list('id', 'last_updated'))
    changes = {}

    for addon, last_updated in next.items():
        try:
            if current[addon] != last_updated:
                changes[addon] = last_updated
        except KeyError:
            pass

    if not changes:
        return

    log.debug('Updating %s add-ons' % len(changes))
    # Update + invalidate.
    qs = Addon.objects.filter(id__in=changes).no_transforms()
    for addon in qs:
        addon.update(last_updated=changes[addon.id])


@use_primary_db
def addon_last_updated():
    next = {}
    for q in Addon._last_updated_queries().values():
        for addon, last_updated in q.values_list('id', 'last_updated'):
            next[addon] = last_updated

    _change_last_updated(next)

    # Get anything that didn't match above.
    other = (Addon.objects.filter(last_updated__isnull=True)
             .values_list('id', 'created'))
    _change_last_updated(dict(other))


def update_addon_appsupport():
    # Find all the add-ons that need their app support details updated.
    newish = (Q(last_updated__gte=F('appsupport__created')) |
              Q(appsupport__created__isnull=True))
    # Search providers don't list supported apps.
    has_app = Q(versions__apps__isnull=False) | Q(type=amo.ADDON_SEARCH)
    has_file = Q(versions__files__status__in=amo.VALID_FILE_STATUSES)
    good = Q(has_app, has_file) | Q(type=amo.ADDON_PERSONA)
    ids = (Addon.objects.valid().distinct()
           .filter(newish, good).values_list('id', flat=True))

    task_log.info('Updating appsupport for %d new-ish addons.' % len(ids))
    ts = [_update_appsupport.subtask(args=[chunk])
          for chunk in chunked(ids, 20)]
    group(ts).apply_async()


def update_all_appsupport():
    from .tasks import update_appsupport
    ids = sorted(set(AppSupport.objects.values_list('addon', flat=True)))
    task_log.info('Updating appsupport for %s addons.' % len(ids))
    for idx, chunk in enumerate(chunked(ids, 100)):
        if idx % 10 == 0:
            task_log.info('[%s/%s] Updating appsupport.'
                          % (idx * 100, len(ids)))
        update_appsupport(chunk)


@task
def _update_appsupport(ids, **kw):
    from .tasks import update_appsupport
    task_log.info('Updating appsupport for %d of new-ish addons.' % len(ids))
    update_appsupport(ids)


def hide_disabled_files():
    # If an add-on or a file is disabled, it should be moved to
    # GUARDED_ADDONS_PATH so it's not publicly visible.
    q = (Q(version__addon__status=amo.STATUS_DISABLED) |
         Q(version__addon__disabled_by_user=True))
    ids = (File.objects.filter(q | Q(status=amo.STATUS_DISABLED))
           .values_list('id', flat=True))
    for chunk in chunked(ids, 300):
        qs = File.objects.filter(id__in=chunk)
        qs = qs.select_related('version')
        for f in qs:
            f.hide_disabled_file()


def unhide_disabled_files():
    # Files are getting stuck in /guarded-addons for some reason. This job
    # makes sure guarded add-ons are supposed to be disabled.
    log = olympia.core.logger.getLogger('z.files.disabled')
    q = (Q(version__addon__status=amo.STATUS_DISABLED) |
         Q(version__addon__disabled_by_user=True))
    files = set(File.objects.filter(q | Q(status=amo.STATUS_DISABLED))
                .values_list('version__addon', 'filename'))
    for filepath in walkfiles(settings.GUARDED_ADDONS_PATH):
        filepath = force_text(filepath)
        addon, filename = filepath.split('/')[-2:]
        if tuple([int(addon), filename]) not in files:
            log.warning(u'File that should not be guarded: %s.', filepath)
            try:
                file_ = (File.objects.select_related('version__addon')
                         .get(version__addon=addon, filename=filename))
                file_.unhide_disabled_file()
            except File.DoesNotExist:
                log.warning(u'File object does not exist for: %s.' % filepath)
            except Exception:
                log.error(u'Could not unhide file: %s.' % filepath,
                          exc_info=True)


def deliver_hotness():
    """
    Calculate hotness of all add-ons.

    a = avg(users this week)
    b = avg(users three weeks before this week)
    hotness = (a-b) / b if a > 1000 and b > 1 else 0
    """
    frozen = set(f.id for f in FrozenAddon.objects.all())
    all_ids = list((Addon.objects.exclude(type=amo.ADDON_PERSONA)
                   .filter(status__in=amo.VALID_ADDON_STATUSES)
                   .values_list('id', flat=True)))
    now = datetime.now()
    one_week = now - timedelta(days=7)
    four_weeks = now - timedelta(days=28)
    for ids in chunked(all_ids, 300):
        addons = Addon.objects.filter(id__in=ids).no_transforms()
        ids = [a.id for a in addons if a.id not in frozen]
        qs = (UpdateCount.objects.filter(addon__in=ids)
              .values_list('addon').annotate(Avg('count')))
        thisweek = dict(qs.filter(date__gte=one_week))
        threeweek = dict(qs.filter(date__range=(four_weeks, one_week)))
        for addon in addons:
            this, three = thisweek.get(addon.id, 0), threeweek.get(addon.id, 0)
            if this > 1000 and three > 1:
                addon.update(hotness=(this - three) / float(three))
            else:
                addon.update(hotness=0)
        # Let the database catch its breath.
        time.sleep(10)


def reindex_addons(index=None, addon_type=None):
    from . import tasks
    ids = Addon.unfiltered.values_list('id', flat=True)
    if addon_type:
        ids = ids.filter(type=addon_type)
    ts = [tasks.index_addons.subtask(args=[chunk], kwargs=dict(index=index))
          for chunk in chunked(sorted(list(ids)), 150)]
    group(ts).apply_async()


def cleanup_image_files():
    """
    Clean up all header images files for themes.

    We use these images to asynchronuously generate thumbnails with
    tasks, here we delete images that are older than one day.

    """
    log.info('Removing one day old temporary image files for themes.')
    for folder in ('persona_header', ):
        root = os.path.join(settings.TMP_PATH, folder)
        if not os.path.exists(root):
            continue
        for path in os.listdir(root):
            full_path = os.path.join(root, path)
            age = time.time() - os.stat(full_path).st_atime
            if age > 60 * 60 * 24:  # One day.
                log.debug('Removing image file: %s, %dsecs old.' %
                          (full_path, age))
                os.unlink(full_path)
