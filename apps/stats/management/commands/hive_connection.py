import codecs
from datetime import datetime

import commonware.log
import pyhs2
from pyhs2 import connections, cursor
from pyhs2.TCLIService.ttypes import TFetchOrientation, TFetchResultsReq

from django.conf import settings

log = commonware.log.getLogger('adi.export')


# This class and the following are needed because the pyhs2 lib doesn't return
# a generator, but a full list! Doing this allows us to return a generator.
class YieldedCursor(cursor.Cursor):
    """Override the fetch method to return a generator."""

    def fetch(self):
        fetchReq = TFetchResultsReq(operationHandle=self.operationHandle,
                                    orientation=TFetchOrientation.FETCH_NEXT,
                                    maxRows=100000)

        while True:
            resultsRes = self.client.FetchResults(fetchReq)
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


def query_to_file(query, filepath, sep):
    start = datetime.now()  # Measure the time to run the script.
    with ClevererConnection(
            host=settings.HIVE_CONNECTION['host'],
            port=settings.HIVE_CONNECTION['port'],
            user=settings.HIVE_CONNECTION['user'],
            password=settings.HIVE_CONNECTION['password'],
            authMechanism=settings.HIVE_CONNECTION['auth_mechanism']) as conn:
        log.info('Storing hive results in %s' % filepath)
        num_reqs = 0
        with codecs.open(filepath, 'w', encoding='utf8') as f:
            with conn.cursor() as cur:
                cur.execute(query)
                for row in cur.fetch():
                    num_reqs += 1
                    if (num_reqs % 1000000) == 0:
                        log.info('Processed %s requests' % num_reqs)
                    f.write(sep.join(str(col) for col in row))
                    f.write('\n')

    log.info('Stored a total of %s requests' % num_reqs)
    log.debug('Total processing time: %s' % (datetime.now() - start))
