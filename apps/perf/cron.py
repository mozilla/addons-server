from datetime import date
from itertools import groupby

from django.db.models import Max

import cronjobs
from celery.messaging import establish_connection

from amo.utils import chunked
from .models import Performance
from . import tasks


@cronjobs.register
def update_perf():
    # The baseline is where addon_id is null. Find the latest test run so we
    # can update from all the latest perf results.
    last_update = (Performance.objects.filter(addon=None)
                   .aggregate(max=Max('created'))['max'])
    last_update = date(*last_update.timetuple()[:3])

    qs = (Performance.objects.filter(created__gte=last_update)
          .values_list('addon', 'osversion', 'average'))
    results = [(addon, list(rows)) for addon, rows
               in groupby(sorted(qs), key=lambda x: x[0])]

    baseline = dict((os, avg) for _, os, avg in qs.filter(addon=None))

    with establish_connection() as conn:
        for chunk in chunked(results, 25):
            tasks.update_perf.apply_async(args=[baseline, chunk],
                                          connection=conn)
