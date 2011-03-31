from django import http
from django.db.models import Avg
from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo
import redisutils

from addons.models import Addon

from .models import Performance, PerformanceOSVersion


@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):
    addons = (Addon.objects.listed(request.APP)
              .filter(ts_slowness__isnull=False).order_by('-ts_slowness'))
    addons = get_list_or_404(addons[:50])
    ids = [a.id for a in addons]
    redis = redisutils.connections['master']
    os_perf = dict(zip(ids, redis.hmget(Performance.ALL_PLATFORMS, ids)))
    platforms = dict((unicode(p), p.id)
                     for p in PerformanceOSVersion.uncached.all())
    return jingo.render(request, 'perf/index.html',
        dict(addons=addons, os_perf=os_perf, platforms=platforms,
             show_os=any(os_perf.values())))
