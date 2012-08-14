import jingo

import mkt
from mkt.webapps.models import Webapp


# TODO: Cache this soooo hard.
def home(request):
    """The home page."""
    if not getattr(request, 'can_view_consumer', True):
        return jingo.render(request, 'home/home_walled.html')
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
    featured = Webapp.featured(region=region)
    popular = Webapp.popular(region=region)[:10]
    latest = Webapp.latest(region=region)[:10]
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
        'popular': popular,
        'latest': latest
    })
