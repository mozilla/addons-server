import jingo

from django.shortcuts import redirect

from amo.urlresolvers import reverse

from mkt.webapps.models import Webapp


def home(request):
    """The home page."""
    if not getattr(request, 'can_view_consumer', True):
        return redirect(reverse('mkt.developers.index'))
    featured = Webapp.featured('home')[:3]
    popular = Webapp.popular()[:6]
    return jingo.render(request, 'home/home.html', {
        'featured': featured,
        'popular': popular
    })
