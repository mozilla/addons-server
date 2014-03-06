from django.shortcuts import render

from waffle.decorators import waffle_switch

import amo
from amo.decorators import permission_required
from amo.utils import paginate

from mkt.developers.models import PreloadTestPlan


@permission_required('Operators', '*')
@waffle_switch('preload-apps')
def preloads(request):
    preloads = (PreloadTestPlan.objects.filter(status=amo.STATUS_PUBLIC)
                                       .order_by('addon__name'))
    preloads = paginate(request, preloads, per_page=20)

    return render(request, 'operators/preloads.html', {'preloads': preloads})
