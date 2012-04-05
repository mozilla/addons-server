import jingo

from addons.models import Addon


def home(request):
    """The home page."""
    featured = []
    popular= []
    return jingo.render(request, 'home/home.html', {'featured': featured,
                        'popular': popular})