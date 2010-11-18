from django.shortcuts import get_list_or_404
from django.views.decorators.cache import cache_control

import jingo

from addons.models import Addon

from .models import Performance


@cache_control(max_age=60 * 60 * 24)  # Cache for a day.
def index(request):
    addons = (Addon.objects.listed(request.APP)
              .filter(performance__average__isnull=False)
              .order_by('-performance__average')[:50])  # LEFT OUTER :(
    addons = get_list_or_404(addons)
    qs = Performance.objects.filter(addon__in=[a.id for a in addons])
    perfs = dict((p.addon_id, p) for p in qs)
    return jingo.render(request, 'perf/index.html',
                        dict(addons=addons, perfs=perfs, baseline=1.2))
