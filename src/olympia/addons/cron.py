import itertools

from datetime import date

import waffle

from django.db import connection
from django.db.models import F, Q, Sum, Value, IntegerField
from celery import group

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, FrozenAddon
from olympia.addons.tasks import (
    update_addon_average_daily_users as _update_addon_average_daily_users,
    update_addon_total_downloads as _update_addon_total_downloads,
    update_appsupport, update_addon_hotness as _update_addon_hotness)
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import chunked
from olympia.files.models import File
from olympia.stats.utils import (
    get_addons_and_average_daily_users_from_bigquery,
    get_averages_by_addon_from_bigquery)
from olympia.lib.es.utils import raise_if_reindex_in_progress


log = olympia.core.logger.getLogger('z.cron')
task_log = olympia.core.logger.getLogger('z.task')


def update_addon_average_daily_users(chunk_size=250):
    """Update add-ons ADU totals."""
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    counts = dict(
        # In order to reset the `average_daily_users` values of add-ons that
        # don't exist in BigQuery, we prepare a set of `(guid, 0)` for most
        # add-ons.
        Addon.objects
        .filter(type__in=amo.ADDON_TYPES_WITH_STATS)
        .exclude(guid__isnull=True)
        .exclude(guid__exact='')
        .exclude(average_daily_users=0)
        .annotate(count=Value(0, IntegerField()))
        .values_list('guid', 'count')
        # Just to make order predictable in tests, we order by id. This
        # matches the GROUP BY being generated so it should be safe.
        .order_by('id')
    )
    # Update the `counts` with values from BigQuery.
    counts.update(get_addons_and_average_daily_users_from_bigquery())
    counts = list(counts.items())

    log.info('Preparing update of `average_daily_users` for %s add-ons.',
             len(counts))

    create_chunked_tasks_signatures(
        _update_addon_average_daily_users, counts, chunk_size
    ).apply_async()


def update_addon_total_downloads():
    """Update add-on total and average downloads."""
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    if waffle.switch_is_active('use-bigquery-for-download-stats-cron'):
        log.info('Not running `update_addon_total_downloads()` because waffle '
                 'switch is active.')
        return

    qs = (
        Addon.objects
             .annotate(sum_download_count=Sum('downloadcount__count'))
             .values_list('id', 'sum_download_count')
             .order_by('id')
    )
    ts = [_update_addon_total_downloads.subtask(args=[chunk])
          for chunk in chunked(qs, 250)]
    group(ts).apply_async()


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

    log.info('Updating %s add-ons' % len(changes))
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
    good = Q(has_app, has_file)
    ids = (Addon.objects.valid().distinct()
           .filter(newish, good).values_list('id', flat=True))

    task_log.info('Updating appsupport for %d new-ish addons.' % len(ids))
    ts = [update_appsupport.subtask(args=[chunk])
          for chunk in chunked(ids, 20)]
    group(ts).apply_async()


def hide_disabled_files():
    """
    Move files (on filesystem) belonging to disabled files (in database) to the
    correct place if necessary, so they they are not publicly accessible
    any more.

    See also unhide_disabled_files().
    """
    ids = (File.objects.filter(
        Q(version__addon__status=amo.STATUS_DISABLED) |
        Q(version__addon__disabled_by_user=True) |
        Q(status=amo.STATUS_DISABLED)).values_list('id', flat=True))
    for chunk in chunked(ids, 300):
        qs = File.objects.select_related('version').filter(id__in=chunk)
        for file_ in qs:
            # This tries to move the file to the disabled location. If it
            # didn't exist at the source, it will catch the exception, log it
            # and continue.
            file_.hide_disabled_file()


def unhide_disabled_files():
    """
    Move files (on filesystem) belonging to public files (in database) to the
    correct place if necessary, so they they publicly accessible.

    See also hide_disabled_files().
    """
    ids = (File.objects.exclude(
        Q(version__addon__status=amo.STATUS_DISABLED) |
        Q(version__addon__disabled_by_user=True) |
        Q(status=amo.STATUS_DISABLED)).values_list('id', flat=True))
    for chunk in chunked(ids, 300):
        qs = File.objects.select_related('version').filter(id__in=chunk)
        for file_ in qs:
            # This tries to move the file to the public location. If it
            # didn't exist at the source, it will catch the exception, log it
            # and continue.
            file_.unhide_disabled_file()


def update_addon_hotness(chunk_size=300):
    """
    Calculate hotness of all add-ons.

    a = avg(users this week)
    b = avg(users three weeks before this week)
    threshold = 250 if addon type is theme, else 1000
    hotness = (a-b) / b if a > threshold and b > 1 else 0
    """
    frozen_guids = list(
        set(fa.addon.guid for fa in FrozenAddon.objects.all() if fa.addon.guid)
    )
    log.info('Found %s frozen add-on GUIDs.', len(frozen_guids))

    amo_guids = (
        Addon.objects.exclude(guid__in=frozen_guids)
        .exclude(guid__isnull=True)
        .exclude(guid__exact='')
        .exclude(hotness=0)
        .values_list('guid', flat=True)
    )
    averages = {
        guid: {'avg_this_week': 1, 'avg_three_weeks_before': 1}
        for guid in amo_guids
    }
    log.info('Found %s add-on GUIDs in AMO DB.', len(averages))

    bq_averages = get_averages_by_addon_from_bigquery(
        today=date.today(), exclude=frozen_guids
    )
    log.info(
        'Found %s add-on GUIDs with averages in BigQuery.', len(bq_averages)
    )

    averages.update(bq_averages)
    log.info('Preparing update of `hotness` for %s add-ons.', len(averages))

    create_chunked_tasks_signatures(
        _update_addon_hotness, averages.items(), chunk_size
    ).apply_async()


def update_addon_weekly_downloads():
    """
    Update 7-day add-on download counts.
    """
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    raise_if_reindex_in_progress('amo')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT addon_id, SUM(count) AS weekly_count
            FROM download_counts
            WHERE `date` >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY addon_id
            ORDER BY addon_id""")
        counts = cursor.fetchall()

    addon_ids = [r[0] for r in counts]

    if not addon_ids:
        return

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, 0
            FROM addons
            WHERE id NOT IN %s""", (addon_ids,))
        counts += cursor.fetchall()

        cursor.execute("""
            CREATE TEMPORARY TABLE tmp_wd
            (addon_id INT PRIMARY KEY, count INT)""")
        cursor.execute('INSERT INTO tmp_wd VALUES %s' %
                       ','.join(['(%s,%s)'] * len(counts)),
                       list(itertools.chain(*counts)))

        cursor.execute("""
            UPDATE addons INNER JOIN tmp_wd
                ON addons.id = tmp_wd.addon_id
            SET weeklydownloads = tmp_wd.count""")
        cursor.execute("DROP TABLE IF EXISTS tmp_wd")
