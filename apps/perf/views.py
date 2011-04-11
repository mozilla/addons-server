from django import http
from django.conf import settings
from django.db.models import Avg
from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo
import redisutils

from addons.models import Addon

from .models import Performance, PerformanceOSVersion


@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):

    # By default don't show less than 25; bug 647398
    threshold = getattr(settings, 'PERF_THRESHOLD', 25)

    addons = (Addon.objects.listed(request.APP)
              .filter(ts_slowness__gte=threshold).order_by('-ts_slowness'))
    addons = get_list_or_404(addons[:50])

    ids = [a.id for a in addons]
    redis = redisutils.connections['master']
    os_perf = dict(zip(ids, redis.hmget(Performance.ALL_PLATFORMS, ids)))
    platforms = dict((unicode(p), p.id)
                     for p in PerformanceOSVersion.uncached.all())
    return jingo.render(request, 'perf/index.html',
        dict(addons=addons, os_perf=os_perf, platforms=platforms,
             show_os=any(os_perf.values())))
