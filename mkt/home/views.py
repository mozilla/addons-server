import jingo

import mkt
from constants.applications import DEVICE_MOBILE
from mkt.webapps.models import Webapp


def _add_mobile_filter(request, qs):
    if request.MOBILE:
        qs = qs.filter(device=DEVICE_MOBILE.id,
                       uses_flash=False)
    return qs


# TODO: Cache this soooo hard.
def home(request):
    """The home page."""
    if not getattr(request, 'can_view_consumer', True):
        return jingo.render(request, 'home/home_walled.html')
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
    featured = Webapp.featured(region=region, cat=None)[:9]
    popular = _add_mobile_filter(request,
                                 Webapp.popular(region=region, gaia=request.GAIA))[:10]
    latest = _add_mobile_filter(request,
                                Webapp.latest(region=region, gaia=request.GAIA))[:10]
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
    })
