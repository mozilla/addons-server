import time

from datetime import date

from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce

import waffle

from celery import group

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, FrozenAddon
from olympia.addons.tasks import (
    update_addon_average_daily_users as _update_addon_average_daily_users,
    update_addon_download_totals as _update_addon_download_totals,
    update_appsupport)
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import chunked
from olympia.files.models import File
from olympia.stats.utils import (
    get_addons_and_average_daily_users_from_bigquery,
    get_averages_by_addon_from_bigquery)


log = olympia.core.logger.getLogger('z.cron')
task_log = olympia.core.logger.getLogger('z.task')


def update_addon_average_daily_users():
    """Update add-ons ADU totals."""
    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    # BigQuery does not have data for add-ons with type other than those in
    # `ADDON_TYPES_WITH_STATS` so we use download counts instead.
    # See: https://github.com/mozilla/addons-server/issues/14609
    amo_counts = dict(
        Addon.objects
        .exclude(type__in=amo.ADDON_TYPES_WITH_STATS)
        .exclude(guid__isnull=True)
        .exclude(guid__exact='')
        .annotate(count=Coalesce(Sum('downloadcount__count'), 0))
        .values_list('guid', 'count')
        # Just to make order predictable in tests, we order by id. This
        # matches the GROUP BY being generated so it should be safe.
        .order_by('id')
    )
    counts = dict(get_addons_and_average_daily_users_from_bigquery())
    counts.update(amo_counts)
    counts = list(counts.items())

    ts = [
        _update_addon_average_daily_users.subtask(args=[chunk])
        for chunk in chunked(counts, 250)
    ]
    group(ts).apply_async()


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


def deliver_hotness():
    """
    Calculate hotness of all add-ons.

    a = avg(users this week)
    b = avg(users three weeks before this week)
    threshold = 250 if addon type is theme, else 1000
    hotness = (a-b) / b if a > threshold and b > 1 else 0
    """
    frozen = set(f.addon_id for f in FrozenAddon.objects.all())
    averages = get_averages_by_addon_from_bigquery(today=date.today())
    addons = (
        Addon.objects.filter(guid__in=averages.keys())
        .filter(status__in=amo.REVIEWED_STATUSES)
        .exclude(id__in=frozen)
    )

    for addon in addons:
        average = averages.get(addon.guid)
        this = average['avg_this_week']
        three = average['avg_three_weeks_before']

        # Update the hotness score but only update hotness if necessary. We
        # don't want to cause unnecessary re-indexes.
        threshold = 250 if addon.type == amo.ADDON_STATICTHEME else 1000
        if this > threshold and three > 1:
            hotness = (this - three) / float(three)
            if addon.hotness != hotness:
                addon.update(hotness=hotness)
        else:
            if addon.hotness != 0:
                addon.update(hotness=0)

        # Let the database catch its breath.
        time.sleep(10)
