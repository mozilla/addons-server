from django import http
from django.conf import settings
from django.db.models import Avg
from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo
import redisutils

import amo
from addons.models import Addon

from .models import Performance, PerformanceOSVersion


# TODO(wraithan): remove this as the code the powers this is no longer around
@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):
    if settings.PERFORMANCE_NOTES == False:
        return jingo.render(request, 'perf/index.html', {'addons': []})
    # By default don't show less than 25; bug 647398
    threshold = Performance.get_threshold()

    addons = (Addon.objects.listed(request.APP, *amo.MIRROR_STATUSES)
              .filter(ts_slowness__gte=threshold)
              .order_by('-ts_slowness')[:50])

    ctx = {'addons': addons}

    if addons:
        ids = [a.id for a in addons]
        redis = redisutils.connections['master']
        os_perf = dict(zip(ids, redis.hmget(Performance.ALL_PLATFORMS, ids)))
        platforms = dict((unicode(p), p.id)
                         for p in PerformanceOSVersion.uncached.all())
        ctx.update(
            os_perf=os_perf,
            platforms=platforms,
            show_os=any(os_perf.values()),
        )

    return jingo.render(request, 'perf/index.html', ctx)
