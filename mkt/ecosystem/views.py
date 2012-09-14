from django.shortcuts import get_object_or_404

import commonware.log
import jingo

from .models import MdnCache
from .tasks import locales


log = commonware.log.getLogger('z.ecosystem')


def landing(request):
    """Developer Hub landing page."""
    return jingo.render(request, 'ecosystem/landing.html')


def partners(request):
    """Landing page for partners."""
    return jingo.render(request, 'ecosystem/partners.html',
           {'page': 'partners', 'category': 'publish'})


def support(request):
    """Landing page for support."""
    return jingo.render(request, 'ecosystem/support.html',
           {'page': 'support', 'category': 'build'})


def documentation(request, page=None):
    """Page template for all content that is extracted from MDN's API."""
    if not page:
        page = 'html5'

    if request.LANG:
        locale = request.LANG.split('-')[0]
        if not locale in locales:
            locale = 'en-US'
    else:
        locale = 'en-US'

    data = get_object_or_404(MdnCache, name=page, locale=locale)

    if page in ('html5', 'manifests', 'manifest_faq', 'firefox_os',
                'tutorial_general', 'tutorial_weather', 'tutorial_serpent',
                'devtools', 'templates'):
        category = 'build'
    elif page in ('principles', 'purpose', 'patterns', 'references',
                  'custom_elements'):
        category = 'design'
    else:
        category = 'publish'

    ctx = {
        'page': page,
        'title': data.title,
        'content': data.content,
        'category': category
    }

    return jingo.render(request, 'ecosystem/documentation.html', ctx)
