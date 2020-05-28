from django.core.management.base import BaseCommand

from celery import group

import olympia.core.logger
from olympia.stats.indexers import DownloadCountIndexer, UpdateCountIndexer


log = olympia.core.logger.getLogger('z.stats')

HELP = """\
Start tasks to index stats. Without constraints, everything will be
processed.


To limit the add-ons:

    `--addons=1865,2848,..,1843`

To limit the  date range:

    `--date=2011-08-15` or `--date=2011-08-15:2011-08-22`
"""


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
        tasks = []
        for indexer in (UpdateCountIndexer, DownloadCountIndexer):
            index_data_tasks = indexer.reindex_tasks_group(
                index_name=index, addons=addons, dates=dates)
            # Unwrap task group to return and execute a single one at the end.
            tasks.extend(index_data_tasks.tasks)
        group(tasks).apply_async()
