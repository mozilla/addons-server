from django import http
from django.db.models import Avg
from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo

from addons.models import Addon

from .models import Performance


@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):
    addons = (Addon.objects.listed(request.APP)
              .filter(ts_slowness__isnull=False).order_by('-ts_slowness'))
    addons = get_list_or_404(addons[:50])
    return jingo.render(request, 'perf/index.html',
                        dict(addons=addons))
