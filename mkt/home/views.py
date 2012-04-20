import jingo
import waffle

import amo
from addons.models import Category
from bandwagon.models import Collection

from mkt.developers.views import home as devhub_home
from mkt.webapps.models import Webapp


def home(request):
    """The home page."""
    if not waffle.switch_is_active('unleash-consumer'):
        return devhub_home
    try:
        featured = Collection.objects.get(author__username='mozilla',
            slug='webapps_home', type=amo.COLLECTION_FEATURED)
    except Collection.DoesNotExist:
        featured = []
    if featured:
        featured = featured.addons.filter(status=amo.STATUS_PUBLIC,
                                          disabled_by_user=False)[:30]
    popular = (Webapp.objects.order_by('-weekly_downloads')
               .filter(status=amo.STATUS_PUBLIC, disabled_by_user=False))[:6]
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP)
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
        'popular': popular,
        'categories': categories,
    })
