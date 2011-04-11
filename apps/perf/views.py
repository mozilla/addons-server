from django import http
from django.conf import settings
from django.db.models import Avg
from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo

from addons.models import Addon

from .models import Performance


@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):

    # By default don't show less than 25; bug 647398
    threshold = getattr(settings, 'PERF_THRESHOLD', 25)

    addons = (Addon.objects.listed(request.APP)
              .filter(ts_slowness__gte=threshold).order_by('-ts_slowness'))
    addons = get_list_or_404(addons[:50])
    return jingo.render(request, 'perf/index.html',
                        dict(addons=addons))
