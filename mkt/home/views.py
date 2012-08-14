import jingo

<<<<<<< HEAD
import mkt
=======
from constants.applications import DEVICE_MOBILE
>>>>>>> Exclude tablet/desktop from mobile listings. (bug 767620)
from mkt.webapps.models import Webapp


def _add_mobile_filter(request, qs):
    if request.MOBILE:
        qs = qs.filter(device=DEVICE_MOBILE.id)
    return qs


# TODO: Cache this soooo hard.
def home(request):
    """The home page."""
    if not getattr(request, 'can_view_consumer', True):
        return jingo.render(request, 'home/home_walled.html')
<<<<<<< HEAD
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
    featured = Webapp.featured(region=region)
    popular = Webapp.popular(region=region)[:10]
    latest = Webapp.latest(region=region)[:10]
=======
    featured = Webapp.featured(cat=None)
    popular = _add_mobile_filter(request, Webapp.popular())[:10]
    latest = _add_mobile_filter(request, Webapp.latest())[:10]
>>>>>>> Exclude tablet/desktop from mobile listings. (bug 767620)
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
        'popular': popular,
        'latest': latest
    })
