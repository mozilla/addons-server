from datetime import date
from itertools import groupby
import logging

from django.db.models import Max

import cronjobs
from celery.task.sets import TaskSet

from amo.utils import chunked
from .models import Performance
from . import tasks


task_log = logging.getLogger('z.task')


@cronjobs.register
def update_perf():
    # The baseline is where addon_id is null. Find the latest test run so we
    # can update from all the latest perf results.
    last_update = (Performance.objects.filter(addon=None)
                   .aggregate(max=Max('created'))['max'])
    if not last_update:
        task_log.error('update_perf aborted, no last_update')
        return

    last_update = date(*last_update.timetuple()[:3])

    qs = (Performance.objects.filter(created__gte=last_update)
          .values_list('addon', 'osversion', 'average'))
    results = [(addon, list(rows)) for addon, rows
               in groupby(sorted(qs), key=lambda x: x[0])]

    baseline = dict((os, avg) for _, os, avg in qs.filter(addon=None))

    ts = [tasks.update_perf.subtask(args=[baseline, chunk])
          for chunk in chunked(results, 25)]
    TaskSet(ts).apply_async()
