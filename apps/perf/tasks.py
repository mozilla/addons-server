import logging

from celeryutils import task

from addons.models import Addon

log = logging.getLogger('z.perf.task')


@task(rate_limit='1/s')
def update_perf(baseline, perf, **kw):
    log.info('[%s@%s] Updating perf' %
             (len(perf), update_perf.rate_limit))
    for addon, rows in perf:
        if addon is None:
            continue
        deltas = [(avg - baseline[os]) / float(baseline[os])
                  for _, os, avg in rows]
        if any(d < 0 for d in deltas):
            slowness = None
        else:
            slowness = sum(deltas) / len(deltas) * 100
        Addon.objects.filter(pk=addon).update(ts_slowness=slowness)
