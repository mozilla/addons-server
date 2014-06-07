import logging
from datetime import date, timedelta
from optparse import make_option

from django.core.management.base import BaseCommand
from django.db.models import Max, Min

from celery.task.sets import TaskSet

from amo.utils import chunked
from stats.models import (CollectionCount, DownloadCount, ThemeUserCount,
                          UpdateCount)
from stats.tasks import (index_collection_counts, index_download_counts,
                         index_theme_user_counts, index_update_counts)

log = logging.getLogger('z.stats')

# Number of days of stats to process in one chunk if we're indexing everything.
STEP = 5

# Number of elements to index at once in ES. The size of a dict to send to ES
# should be less than 1000 bytes, and the max size of messages to send to ES
# can be retrieved with the following command (look for
# "max_content_length_in_bytes"):
#  curl http://HOST:PORT/_nodes/?pretty
CHUNK_SIZE = 10000

HELP = """\
Start tasks to index stats. Without constraints, everything will be
processed.


To limit the add-ons:

    `--addons=1865,2848,..,1843`

To limit the  date range:

    `--date=2011-08-15` or `--date=2011-08-15:2011-08-22`
"""


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--addons',
                    help='Add-on ids to process. Use commas to separate '
                         'multiple ids.'),
        make_option('--date',
                    help='The date or date range to process. Use the format '
                         'YYYY-MM-DD for a single date or '
                         'YYYY-MM-DD:YYYY-MM-DD to index a range of dates '
                         '(inclusive).'),
        make_option('--fixup', action='store_true',
                    help='Find and index rows we missed.'),
        make_option('--index',
                    help='Optional index name to use.'),
    )
    help = HELP

    def handle(self, *args, **kw):
        if kw.get('fixup'):
            fixup()

        addons, dates, index = kw['addons'], kw['date'], kw['index']

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
                    create_tasks(task, list(qs.filter(**{
                                            '%s__range' % date_field:
                                            date_range})), index)
            else:
                create_tasks(task, list(qs), index)


def create_tasks(task, qs, index):
    ts = [task.subtask(args=[chunk, index])
          for chunk in chunked(qs, CHUNK_SIZE)]
    TaskSet(ts).apply_async()


def fixup():
    queries = [(UpdateCount, index_update_counts),
               (DownloadCount, index_download_counts),
               (ThemeUserCount, index_theme_user_counts)]

    for model, task in queries:
        all_addons = model.objects.distinct().values_list('addon', flat=True)
        for addon in all_addons:
            qs = model.objects.filter(addon=addon)
            search = model.search().filter(addon=addon)
            if qs.count() != search.count():
                all_ids = list(qs.values_list('id', flat=True))
                search_ids = list(search.values()[:5000])
                ids = set(all_ids) - set(search_ids)
                log.info('Missing %s rows for %s.' % (len(ids), addon))
                create_tasks(task, list(ids))
