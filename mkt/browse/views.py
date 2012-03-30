import jingo

from django.shortcuts import get_object_or_404, redirect

import amo
from addons.models import Category
from mkt.search.views import _app_search


def categories_apps(request, category=None):
    ctx = {}

    if category is not None:
        qs = Category.objects.filter(type=amo.ADDON_WEBAPP)
        ctx['category'] = get_object_or_404(qs, slug=category)

        # Do a search filtered by this category and sort by Weekly Downloads.
        request.GET = request.GET.copy()
        request.GET.update({'cat': ctx['category'].id, 'sort': 'downloads'})

    ctx.update(_app_search(request, ctx['category']))

    # If category is not listed as a facet, then remove redirect to search.
    if ctx.get('redirect'):
        return redirect(ctx['redirect'])

    return jingo.render(request, 'search/results.html', ctx)
