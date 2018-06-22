import random

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max, Min

import olympia.core.logger

from olympia.amo.celery import create_subtasks
from olympia.stats.models import (
    CollectionCount, DownloadCount, ThemeUserCount, UpdateCount)
from olympia.stats.search import CHUNK_SIZE
from olympia.stats.tasks import (
    index_collection_counts, index_download_counts, index_theme_user_counts,
    index_update_counts)


# Number of days of stats to process in one chunk if we're indexing everything.
STEP = 5

HELP = """\
Start tasks to index stats. Without constraints, everything will be
processed.


To limit the add-ons:

    `--addons=1865,2848,..,1843`

To limit the  date range:

    `--date=2011-08-15` or `--date=2011-08-15:2011-08-22`
"""


def index_stats(index, addons=None, dates=None):
    queries = [
        (UpdateCount.objects, index_update_counts,
            {'date': 'date'}),
        (DownloadCount.objects, index_download_counts,
            {'date': 'date'}),
        (ThemeUserCount.objects, index_theme_user_counts,
            {'date': 'date'})
    ]

    if not addons:
        # We can't filter this by addons, so if that is specified,
        # we'll skip that.
        queries.append((CollectionCount.objects, index_collection_counts,
                        {'date': 'date'}))

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
            today = date.today()
            for start in range(0, num_days, STEP):
                stop = start + STEP
                date_range = (today - timedelta(days=stop),
                              today - timedelta(days=start))

                data = list(qs.filter(**{
                    '%s__range' % date_field: date_range
                }))
                create_subtasks(
                    task, data, CHUNK_SIZE,
                    countdown=random.randint(1, 6),
                    task_args=(index,))
        else:
            create_subtasks(
                task, list(qs), CHUNK_SIZE,
                countdown=random.randint(1, 6),
                task_args=(index,))


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
        index_stats(index=index, addons=addons, dates=dates)
