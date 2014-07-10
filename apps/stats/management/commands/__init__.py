import os
from datetime import datetime, timedelta
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand

from .hive_connection import query_to_file


class HiveQueryToFileCommand(BaseCommand):
    """Base command for the "query counts" requests from HIVE, save to disk.

    The data stored locally will then be processed by the
    download_counts_from_file.py or update_counts_from_file.py script.

    """
    option_list = BaseCommand.option_list + (
        make_option('--separator', action='store', type='string', default='\t',
                    dest='separator', help='Field separator in file.'),
        make_option('--date', action='store', type='string',
                    dest='date', help='Date in the YYYY-MM-DD format.'),
        make_option('--limit', action='store', type='int',
                    dest='limit', help='(debug) max number of requests.'),
    )
    filename = None  # Name of the file to save the results to.
    query = None  # Query to run against the hive server.

    def handle(self, *args, **options):
        folder = args[0] if args else 'hive_results'
        folder = os.path.join(settings.NETAPP_STORAGE, 'tmp', folder)
        day = options['date']
        if not day:
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        sep = options['separator']
        limit = options['limit']
        limit_str = ('limit %s' % limit) if limit else ''

        if not os.path.isdir(folder):
            os.makedirs(folder)
        filepath = os.path.join(folder, self.filename)
        return query_to_file(self.query % (day, limit_str), filepath, sep)


def get_date_from_file(filepath, sep):
    """Get the date from the file, which should be the first col."""
    with open(filepath) as f:
        line = f.readline()
        try:
            return line.split(sep)[0]
        except IndexError:
            return None
