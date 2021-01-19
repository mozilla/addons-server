from datetime import date

from django.db.models import Q, Value, IntegerField

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, FrozenAddon
from olympia.addons.tasks import (
    update_addon_average_daily_users as _update_addon_average_daily_users,
    update_addon_hotness as _update_addon_hotness,
    update_addon_weekly_downloads as _update_addon_weekly_downloads,
)
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import chunked
from olympia.files.models import File
from olympia.stats.utils import (
    get_addons_and_average_daily_users_from_bigquery,
    get_addons_and_weekly_downloads_from_bigquery,
    get_averages_by_addon_from_bigquery,
)


log = olympia.core.logger.getLogger('z.cron')
task_log = olympia.core.logger.getLogger('z.task')


def update_addon_average_daily_users(chunk_size=250):
    """Update add-ons ADU totals."""
    counts = dict(
        # In order to reset the `average_daily_users` values of add-ons that
        # don't exist in BigQuery, we prepare a set of `(guid, 0)` for most
        # add-ons.
        Addon.unfiltered.filter(type__in=amo.ADDON_TYPES_WITH_STATS)
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

    log.info('Preparing update of `average_daily_users` for %s add-ons.', len(counts))

    create_chunked_tasks_signatures(
        _update_addon_average_daily_users, counts, chunk_size
    ).apply_async()


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
    other = Addon.objects.filter(last_updated__isnull=True).values_list('id', 'created')
    _change_last_updated(dict(other))


def hide_disabled_files():
    """
    Move files (on filesystem) belonging to disabled files (in database) to the
    correct place if necessary, so they they are not publicly accessible
    any more.

    See also unhide_disabled_files().
    """
    ids = File.objects.filter(
        Q(version__addon__status=amo.STATUS_DISABLED)
        | Q(version__addon__disabled_by_user=True)
        | Q(status=amo.STATUS_DISABLED)
    ).values_list('id', flat=True)
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
    ids = File.objects.exclude(
        Q(version__addon__status=amo.STATUS_DISABLED)
        | Q(version__addon__disabled_by_user=True)
        | Q(status=amo.STATUS_DISABLED)
    ).values_list('id', flat=True)
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
        guid: {'avg_this_week': 1, 'avg_three_weeks_before': 1} for guid in amo_guids
    }
    log.info('Found %s add-on GUIDs in AMO DB.', len(averages))

    bq_averages = get_averages_by_addon_from_bigquery(
        today=date.today(), exclude=frozen_guids
    )
    log.info('Found %s add-on GUIDs with averages in BigQuery.', len(bq_averages))

    averages.update(bq_averages)
    log.info('Preparing update of `hotness` for %s add-ons.', len(averages))

    create_chunked_tasks_signatures(
        _update_addon_hotness, averages.items(), chunk_size
    ).apply_async()


def update_addon_weekly_downloads(chunk_size=250):
    """
    Update 7-day add-on download counts.
    """
    counts = dict(
        # In order to reset the `weekly_downloads` values of add-ons that
        # don't exist in BigQuery, we prepare a set of `(hashed_guid, 0)`
        # for most add-ons.
        Addon.objects.filter(type__in=amo.ADDON_TYPES_WITH_STATS)
        .exclude(guid__isnull=True)
        .exclude(guid__exact='')
        .exclude(weekly_downloads=0)
        .annotate(count=Value(0, IntegerField()))
        .values_list('addonguid__hashed_guid', 'count')
    )
    # Update the `counts` with values from BigQuery.
    counts.update(get_addons_and_weekly_downloads_from_bigquery())
    counts = list(counts.items())

    log.info('Preparing update of `weekly_downloads` for %s add-ons.', len(counts))

    create_chunked_tasks_signatures(
        _update_addon_weekly_downloads, counts, chunk_size
    ).apply_async()
