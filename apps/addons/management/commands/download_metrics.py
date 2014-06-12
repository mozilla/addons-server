import os
from datetime import datetime
from optparse import make_option

import pyhs2
from pyhs2 import connections, cursor
from pyhs2.TCLIService.ttypes import TFetchOrientation, TFetchResultsReq

from django.core.management.base import BaseCommand, CommandError

import commonware.log


log = commonware.log.getLogger('adi.export')


fetch_time = 0  # Used for time reporting.


# This class and the following are needed because the pyhs2 lib doesn't return
# a generator, but a full list! Doing this allows us to return a generator.
class YieldedCursor(cursor.Cursor):
    """Override the fetch method to return a generator."""

    def fetch(self):
        max_rows = int(os.getenv('MAX_HIVE_ROWS', 10000))
        fetchReq = TFetchResultsReq(operationHandle=self.operationHandle,
                                    orientation=TFetchOrientation.FETCH_NEXT,
                                    maxRows=max_rows)

        while True:
            global fetch_time
            # Measure the time it takes to retrieve from hive.
            start = datetime.now()
            resultsRes = self.client.FetchResults(fetchReq)
            fetch_time += (datetime.now() - start).total_seconds()
            if len(resultsRes.results.rows) == 0:
                break
            for row in resultsRes.results.rows:
                rowData = []
                for i, col in enumerate(row.colVals):
                    rowData.append(pyhs2.cursor.get_value(col))
                yield rowData


class ClevererConnection(connections.Connection):
    """Return our own YieldedCursor.

    Yeah, it seems pysh2 isn't dealing with so much data... so there's just a
    huge list returned.

    """

    def cursor(self):
        return YieldedCursor(self.client, self.session)


class Command(BaseCommand):
    """Execute queries on HIVE, and store the results on disk.

    Query the downloads or updates requests for addons on HIVE. These will then
    be processed by other scripts to store counts in the DownloadCount and
    UploadCount objects.

    Usage:
    ./manage.py download_metrics --date YYYY-MM-DD \
                                 --with-updates --with-downloads

    Set a ``MAX_HIVE_ROWS`` environment variable to minimize the network
    latency (default is 10000 rows fetched from hive at once), but it will
    increase the memory footprint.

    """
    help = __doc__

    option_list = BaseCommand.option_list + (
        make_option('--output', action='store', type='string',
                    dest='filename', help='Filename to output to.'),
        make_option('--separator', action='store', type='string', default='\t',
                    dest='separator', help='Field separator in file.'),
        make_option('--date', action='store', type='string',
                    dest='date', help='Date in the YYYY-MM-DD format.'),
        make_option('--with-updates', action='store_true', default=False,
                    dest='with_updates', help='Store update requests.'),
        make_option('--with-downloads', action='store_true', default=False,
                    dest='with_downloads', help='Store download requests.'),
        make_option('--limit', action='store', type='int',
                    dest='limit', help='(debug) max number of requests.'),
    )

    def handle(self, *args, **options):
        day = options['date']
        if not day:
            raise CommandError('You must specify a --date parameter in the '
                               ' YYYY-MM-DD format.')
        filename = options['filename']
        if filename is None:
            filename = day
        sep = options['separator']
        limit = options['limit']
        with_updates = options['with_updates']
        with_downloads = options['with_downloads']
        if not with_updates and not with_downloads:
            raise CommandError('Please specify at least one of --with-updates '
                               'or --with-downloads.')

        with ClevererConnection(host='peach-gw.peach.metrics.scl3.mozilla.com',
                                port=10000,
                                user='aphadke',
                                password='',
                                authMechanism='PLAIN') as conn:
            num_reqs = 0
            with conn.cursor() as cur:
                start = datetime.now()  # Measure the time to run the script.
                if with_downloads:
                    num_reqs += self.process_downloads(
                        cur, day, filename, sep=sep, limit=limit)
                if with_updates:
                    num_reqs += self.process_updates(
                        cur, day, filename, sep=sep, limit=limit)

        total_time = (datetime.now() - start).total_seconds()
        log.info('Stored a total of %s requests' % num_reqs)
        log.debug('Total processing time: %s seconds' % total_time)
        log.debug('Time spent fetching data from hive over the network: %s' %
                  fetch_time)

    def process_updates(self, cur, day, filename, sep, limit=None):
        """Query the update requests and store them on disk."""
        limit = ('limit %s' % limit) if limit else ''
        # We use "concat" and http://a.com in the following request to have
        # fully qualified URLs.
        cur.execute("select count(1), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'id'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'version'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'status'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appID'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appVersion'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appOS'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'locale'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'updateType') "
        "from v2_raw_logs "
        "where domain='versioncheck.addons.mozilla.org' "
        "  and ds='%s' "
        "  and request_url like '/update/VersionCheck.php?%%' "
        "group by "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'id'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'version'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'status'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appID'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appVersion'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'appOS'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'locale'), "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'updateType') "
        "%s" % (day, limit))

        return self.to_file(cur, '%s.updates' % filename, sep)

    def process_downloads(self, cur, day, filename, sep, limit=None):
        """Query the download requests and store them on disk."""
        limit = ('limit %s' % limit) if limit else ''
        # We use "concat" and http://a.com in the following request to have
        # fully qualified URLs.
        cur.execute("select count(1), "
        "  split(request_url,'/')[4], "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'src') "
        "from v2_raw_logs "
        "where domain='addons.mozilla.org' "
        "  and ds='%s' "
        "  and request_url like '/firefox/downloads/file/%%' "
        "  and !(parse_url(concat('http://a.com',request_url), 'QUERY', 'src') LIKE 'sync') "
        "group by "
        "  split(request_url,'/')[4], "
        "  parse_url(concat('http://a.com',request_url), 'QUERY', 'src') "
        "%s" % (day, limit))
        return self.to_file(cur, '%s.downloads' % filename, sep)

    def to_file(self, cur, filename, sep):
        log.info('Storing hive results in %s' % filename)
        count = 0
        with open(filename, 'w') as f:
            for row in cur.fetch():
                count += 1
                if (count % 100000) == 0:
                    log.info('Processed %s requests' % count)
                if None in row:  # Incomplete result: skip.
                    continue
                f.write(sep.join([str(col) for col in row]))
                f.write('\n')

        return count
