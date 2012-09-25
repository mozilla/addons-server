from django import http
from django.shortcuts import get_object_or_404

import jingo

import amo
import mkt
from addons.models import Category

from mkt.home.views import _add_mobile_filter
from mkt.search.views import _app_search
from mkt.webapps.models import Webapp


# Currently unused.
def _landing(request, category=None):
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
    if category:
        category = get_object_or_404(
            Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0),
            slug=category)
        featured = Webapp.featured(cat=category, region=region)
        popular = _add_mobile_filter(request,
            Webapp.popular(cat=category, region=region))
    else:
        popular = _add_mobile_filter(request, Webapp.popular(region=region))
        featured = Webapp.featured(region=region)

    return jingo.render(request, 'browse/landing.html', {
        'category': category,
        'featured': featured[:6],
        'popular': popular[:6]
    })


def _search(request, category=None):
    ctx = {'browse': True}
    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)

    if category is not None:
        qs = Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0)
        ctx['category'] = get_object_or_404(qs, slug=category)
        ctx['featured'] = Webapp.featured(cat=ctx['category'], region=region)

        # Do a search filtered by this category and sort by Weekly Downloads.
        # TODO: Listen to andy and do not modify `request.GET` but at least
        # the traceback is fixed now.
        request.GET = request.GET.copy()
        request.GET.update({'cat': ctx['category'].id})
        if not request.GET.get('sort'):
            request.GET['sort'] = 'downloads'
    else:
        ctx['featured'] = Webapp.featured(region=region)

    ctx.update(_app_search(request, category=ctx.get('category'), browse=True))

    # If category is not listed as a facet, then remove redirect to search.
    if ctx.get('redirect'):
        return http.HttpResponseRedirect(ctx['redirect'])

    return jingo.render(request, 'search/results.html', ctx)


# mushi says there will likely be a landing page at some point otherwise this
# extra function is useless.
def browse_apps(request, category=None):
    return _search(request, category)
