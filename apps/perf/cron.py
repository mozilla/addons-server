from django.db import connections

import cronjobs
import multidb
from celery.messaging import establish_connection

from amo.utils import chunked
from . import tasks


@cronjobs.register
def update_perf():
    cursor = connections[multidb.get_slave()].cursor()
    # The baseline is where addon_id is null.
    cursor.execute(
        "SELECT AVG(average) FROM perf_results WHERE addon_id IS NULL")
    baseline = cursor.fetchone()[0]

    # The perf_results table is a mess right now, so pull out one row
    # for each addon by finding the MAX(created) and then the AVG(average)
    # since there are many rows with the same (addon, created).
    # This scheme completely ignores app, os, and test.
    cursor.execute("""
        SELECT J.addon_id, AVG(average) av FROM perf_results P INNER JOIN
            (SELECT addon_id, MAX(created) c FROM perf_results
             GROUP BY addon_id) J
        ON ((P.addon_id=J.addon_id) AND P.created=J.c)
        WHERE test='ts'
        GROUP BY P.addon_id
        HAVING av > %s""", (baseline,))
    # A bunch of (addon, perf_average) pairs.
    perf = cursor.fetchall()
    with establish_connection() as conn:
        for chunk in chunked(perf, 25):
            tasks.update_perf.apply_async(args=[baseline, chunk],
                                          connection=conn)
    cursor.close()
