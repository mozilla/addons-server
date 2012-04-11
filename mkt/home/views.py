import jingo
import waffle

from mkt.developers.views import home as devhub_home
from mkt.webapps.models import Webapp


def home(request):
    """The home page."""
    if not waffle.switch_is_active('unleash-consumer'):
        return devhub_home
    featured = Webapp.objects.all()
    popular = Webapp.objects.all()
    return jingo.render(request, 'home/home.html', {'featured': featured,
                        'popular': popular})
