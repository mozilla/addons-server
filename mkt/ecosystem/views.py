from django.shortcuts import get_object_or_404

import commonware.log
import jingo

from .models import MdnCache
from .tasks import locales, refresh_mdn_cache, tutorials


log = commonware.log.getLogger('z.ecosystem')


def landing(request):
    """Developer Hub landing page."""
    return jingo.render(request, 'ecosystem/landing.html')


def developers(request):
    """Landing page for developers."""
    return jingo.render(request, 'ecosystem/developers.html')


def building_blocks(request):
    """Landing page for developers."""
    return jingo.render(request,
        'ecosystem/mdn_documentation/building_blocks.html')


def building_xtag(request, xtag=None):
    """Page for using a particular x-tag.
    The process of generating the x-tag title is temporary as these pages
    are not yet on MDN. Once they are officially on there, then we can pull
    everything directly from the database instead.
    """

    if not xtag:
        xtag = 'list'

    return jingo.render(request, 'ecosystem/design/xtag_%s.html' % xtag,
                        {'title': xtag.replace('_', ' ').capitalize()})


def partners(request):
    """Landing page for partners."""
    return jingo.render(request, 'ecosystem/partners.html')


def support(request):
    """Landing page for support."""
    return jingo.render(request, 'ecosystem/support.html')


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

    ctx = {
        'page': page,
        'title': data.title,
        'content': data.content,
    }

    page_name = 'index.html'

    if page in ['design_guidelines', 'purpose_of_your_app',
                'design_principles', 'navigation', 'resources', 'layout',
                'design_patterns']:
        page_name = 'design.html'
    elif page in ['devtools', 'templates', 'web_components']:
        page_name = 'sdk.html'
    elif page in ['mkt_hosting', 'mkt_submission']:
        page_name = 'publish_it.html'

    return jingo.render(request, 'ecosystem/mdn_documentation/%s' %
                        page_name, ctx)
