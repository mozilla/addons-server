import jingo

import mkt
from constants.applications import DEVICE_GAIA, DEVICE_MOBILE
from mkt.webapps.models import Webapp


def _add_mobile_filter(request, qs):
    if request.GAIA:
        qs = qs.filter(device=DEVICE_GAIA.id, uses_flash=False)
    elif request.MOBILE:
        qs = qs.filter(device=DEVICE_MOBILE.id, uses_flash=False)
    return qs


# TODO: Cache this soooo hard.
def home(request):
    """The home page."""
    if not getattr(request, 'can_view_consumer', True):
        return jingo.render(request, 'home/home_walled.html')
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
    import debug
    featured = Webapp.featured(region=region, cat=None,
        mobile=request.MOBILE)
    featured_cnt = len(featured)

    # Show featured apps in multiples of three.
    if request.MOBILE:
        if featured_cnt >= 9:
            featured = featured[:9]
        elif featured_cnt >= 6:
            featured = featured[:6]
        elif featured_cnt >= 3:
            featured = featured[:3]
    else:
        if featured_cnt >= 12:
            featured = featured[:12]
        elif featured_cnt >= 8:
            featured = featured[:8]
        elif featured_cnt >= 4:
            # Once we allow for the giant featured app we'll require at least
            # 5 featured apps on desktop.
            featured = featured[:4]

    return jingo.render(request, 'home/home.html', {
        'featured': featured,
    })
