from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max, Min

from celery import group

import olympia.core.logger
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.stats.models import (
    DownloadCount, ThemeUserCount, UpdateCount)
from olympia.stats.search import CHUNK_SIZE
from olympia.stats.tasks import (
    index_download_counts, index_theme_user_counts, index_update_counts)


log = olympia.core.logger.getLogger('z.stats')

# Number of days of stats to process in one chunk if we're indexing everything.
STEP = 6

HELP = """\
Start tasks to index stats. Without constraints, everything will be
processed.


To limit the add-ons:

    `--addons=1865,2848,..,1843`

To limit the  date range:

    `--date=2011-08-15` or `--date=2011-08-15:2011-08-22`
"""


def gather_index_stats_tasks(index, addons=None, dates=None):
    """
    Return the list of task groups to execute to index statistics for the given
    index/dates/addons.
    """
    queries = [
        (UpdateCount.objects, index_update_counts,
            {'date': 'date'}),
        (DownloadCount.objects, index_download_counts,
            {'date': 'date'}),
        (ThemeUserCount.objects, index_theme_user_counts,
            {'date': 'date'})
    ]

    jobs = []

    for qs, task, fields in queries:
        date_field = fields['date']

        if dates or addons:
            qs = qs.order_by('-%s' % date_field)

        qs = qs.values_list('id', flat=True)

        if addons:
            pks = [int(a.strip()) for a in addons.split(',')]
            qs = qs.filter(addon__in=pks)

        if dates:
            if ':' in dates:
                qs = qs.filter(**{'%s__range' % date_field:
                                  dates.split(':')})
            else:
                qs = qs.filter(**{date_field: dates})

        if not (dates or addons):
            # We're loading the whole world. Do it in stages so we get most
            # recent stats first and don't do huge queries.
            limits = (qs.model.objects.filter(**{'%s__isnull' %
                                                 date_field: False})
                      .extra(where=['%s <> "0000-00-00"' % date_field])
                      .aggregate(min=Min(date_field), max=Max(date_field)))
            # If there isn't any data at all, skip over.
            if not (limits['max'] or limits['min']):
                continue

            num_days = (limits['max'] - limits['min']).days
            for start in range(0, num_days, STEP):
                stop = start + STEP - 1
                date_range = (limits['max'] - timedelta(days=stop),
                              limits['max'] - timedelta(days=start))
                data = list(qs.filter(**{
                    '%s__range' % date_field: date_range
                }))
                if data:
                    jobs.append(create_chunked_tasks_signatures(
                        task, data, CHUNK_SIZE, task_args=(index,)))
        else:
            jobs.append(create_chunked_tasks_signatures(
                task, list(qs), CHUNK_SIZE, task_args=(index,)))
    return jobs


class Command(BaseCommand):
    help = HELP

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--addons',
            help='Add-on ids to process. Use commas to separate multiple ids.')

        parser.add_argument(
            '--date',
            help='The date or date range to process. Use the format '
                 'YYYY-MM-DD for a single date or '
                 'YYYY-MM-DD:YYYY-MM-DD to index a range of dates '
                 '(inclusive).')

        parser.add_argument(
            '--index',
            help='Optional index name to use.')

    def handle(self, *args, **kw):
        addons, dates, index = kw['addons'], kw['date'], kw['index']
        workflow = group(
            gather_index_stats_tasks(index=index, addons=addons, dates=dates)
        )
        workflow.apply_async()
