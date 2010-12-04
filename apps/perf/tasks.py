import logging

from celeryutils import task

from addons.models import Addon

log = logging.getLogger('z.perf.task')


@task(rate_limit='1/s')
def update_perf(baseline, perf, **kw):
    log.info('[%s@%s] Updating perf' %
             (len(perf), update_perf.rate_limit))
    for addon, avg in perf:
        num = (avg - baseline) / baseline
        Addon.objects.filter(pk=addon).update(ts_slowness=100 * num)
