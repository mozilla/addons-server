import jingo

from mkt.webapps.models import Webapp

def home(request):
    """The home page."""
    featured = Webapp.objects.all()
    popular = Webapp.objects.all()
    return jingo.render(request, 'home/home.html', {'featured': featured,
                        'popular': popular})