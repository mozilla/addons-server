import os
from datetime import datetime, timedelta
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand

from .hive_connection import query_to_file

IP_BLACKLIST = """
    -- Mozilla Network
    ip_address NOT LIKE '63.245.208.%' AND
    ip_address NOT LIKE '63.245.209.%' AND
    ip_address NOT LIKE '63.245.21%' AND
    ip_address NOT LIKE '63.245.220.%' AND
    ip_address NOT LIKE '63.245.221.%' AND
    ip_address NOT LIKE '63.245.222.%' AND
    ip_address NOT LIKE '63.245.223.%' AND

    -- Not sure, but grepped an hour of logs, nothing.
    ip_address NOT LIKE '180.92.184.%' AND

    -- CN adm
    ip_address NOT LIKE '59.151.50%' AND
    ip_address NOT IN (
        -- Not sure
        '72.26.221.66',
        '72.26.221.67',

        -- white hat
        '209.10.217.226',

        -- CN lbs
        '223.202.6.11',
        '223.202.6.12',
        '223.202.6.13',
        '223.202.6.14',
        '223.202.6.15',
        '223.202.6.16',
        '223.202.6.17',
        '223.202.6.18',
        '223.202.6.19',
        '223.202.6.20'
    )
"""


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
        folder = os.path.join(settings.TMP_PATH, folder)
        day = options['date']
        if not day:
            day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        sep = options['separator']
        limit = options['limit']
        limit_str = ('limit %s' % limit) if limit else ''

        if not os.path.isdir(folder):
            os.makedirs(folder, 0775)
        if not os.path.isdir(os.path.join(folder, day)):
            os.makedirs(os.path.join(folder, day), 0755)
        filepath = os.path.join(folder, day, self.filename)
        return query_to_file(self.query.format(day=day,
                                               ip_filtering=IP_BLACKLIST,
                                               limit=limit_str),
                             filepath, sep)


def get_date_from_file(filepath, sep):
    """Get the date from the file, which should be the first col."""
    with open(filepath) as f:
        line = f.readline()
        try:
            return line.split(sep)[0]
        except IndexError:
            return None
