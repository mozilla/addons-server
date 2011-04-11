import json
import logging

import redisutils
from celeryutils import task

from addons.models import Addon
from .models import Performance

log = logging.getLogger('z.perf.task')


@task(rate_limit='1/s')
def update_perf(baseline, perf, **kw):
    log.info('[%s@%s] Updating perf' %
             (len(perf), update_perf.rate_limit))
    all_deltas = {}
    for addon, rows in perf:
        if addon is None:
            continue
        deltas = dict((os, (avg - baseline[os]) / float(baseline[os]) * 100)
                       for _, os, avg in rows)
        if any(d < 0 for d in deltas.values()):
            slowness = None
            all_deltas[addon] = None
        else:
            slowness = int(sum(deltas.values()) / len(deltas))
            d = dict((k, int(v)) for k, v in deltas.items())
            # Include the average slowness as key 0.
            d[0] = slowness
            all_deltas[addon] = json.dumps(d, separators=(',', ':'))
        Addon.objects.filter(pk=addon).update(ts_slowness=slowness)

    # Add all the calculated values to redis so we can show per-platform perf.
    redis = redisutils.connections['master']
    redis.hmset(Performance.ALL_PLATFORMS, all_deltas)

    for key, val in all_deltas.items():
        if val is None:
            redis.hdel(Performance.ALL_PLATFORMS, key)
