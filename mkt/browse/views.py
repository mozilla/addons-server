import jingo

from django.shortcuts import get_object_or_404, redirect

import amo
from addons.models import Category

from mkt.search.views import _app_search
from mkt.webapps.models import Webapp


def _landing(request, category=None):
    featured = Webapp.featured('category')
    popular = Webapp.popular()

    if category:
        category = get_object_or_404(
            Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0),
            slug=category)
        featured = featured.filter(category=category)[:6]
        popular = popular.filter(category=category.id)

    return jingo.render(request, 'browse/landing.html', {
        'category': category,
        'featured': featured[:6],
        'popular': popular[:6]
    })


def _search(request, category=None):
    ctx = {'browse': True}

    if category is not None:
        qs = Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0)
        ctx['category'] = get_object_or_404(qs, slug=category)

        # Do a search filtered by this category and sort by Weekly Downloads.
        # TODO: Listen to andy and do not modify `request.GET` but at least
        # the traceback is fixed now.
        request.GET = request.GET.copy()
        request.GET.update({'cat': ctx['category'].id})
        if not request.GET.get('sort'):
            request.GET['sort'] = 'downloads'

    ctx.update(_app_search(request, category=ctx.get('category'), browse=True))

    # If category is not listed as a facet, then remove redirect to search.
    if ctx.get('redirect'):
        return redirect(ctx['redirect'])

    return jingo.render(request, 'search/results.html', ctx)


def browse_apps(request, category=None):
    if request.GET.get('sort'):
        return _search(request, category)
    else:
        return _landing(request, category)
