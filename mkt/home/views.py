import jingo
import waffle

import amo
from addons.models import Category

from mkt.developers.views import home as devhub_home
from mkt.webapps.models import Webapp


def home(request):
    """The home page."""
    if not waffle.switch_is_active('unleash-consumer'):
        return devhub_home
    featured = Webapp.objects.all()[:30]
    popular = Webapp.objects.order_by('-weekly_downloads')[:30]
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP)
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
        'popular': popular,
        'categories': categories,
    })
