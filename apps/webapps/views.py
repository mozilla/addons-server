from django.shortcuts import get_object_or_404

import jingo
from tower import ugettext_lazy as _lazy

import amo
from amo.utils import paginate
import addons.views
import search.views

from addons.models import Category
from browse.views import addon_listing, category_landing, CategoryLandingFilter
from sharing.views import share as share_redirect
from .models import Webapp

TYPE = amo.ADDON_WEBAPP


def es_app_list(request):
    ctx = search.views.app_search_query(request)
    ctx['search_cat'] = 'apps'
    return jingo.render(request, 'webapps/listing.html', ctx)


def app_home(request):
    # TODO: This will someday no longer be the listing page.
    return app_list(request)


class AppCategoryLandingFilter(CategoryLandingFilter):

    opts = (('featured', _lazy(u'Featured')),
            ('downloads', _lazy(u'Most Popular')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Recently Added')))


# TODO(cvan): Implement mobile pages.
# @mobile_template('webapps/{mobile/}listing.html')
def app_list(request, category=None):
    if category is not None:
        q = Category.objects.filter(type=TYPE)
        category = get_object_or_404(q, slug=category)

    sort = request.GET.get('sort')
    if not sort and not request.MOBILE and category and category.count > 4:
        return category_landing(request, category, TYPE,
                                AppCategoryLandingFilter)

    addons, filter = addon_listing(request, [TYPE])
    sorting = filter.field
    src = 'cb-btn-%s' % sorting
    dl_src = 'cb-dl-%s' % sorting

    if category:
        addons = addons.filter(categories__id=category.id)

    addons = paginate(request, addons, count=addons.count())
    ctx = {'section': amo.ADDON_SLUGS[TYPE], 'addon_type': TYPE,
           'category': category, 'addons': addons, 'filter': filter,
           'sorting': sorting, 'sort_opts': filter.opts, 'src': src,
           'dl_src': dl_src, 'search_cat': 'apps'}
    return jingo.render(request, 'browse/extensions.html', ctx)


def app_detail(request, app_slug):
    # TODO: check status.
    webapp = get_object_or_404(Webapp, app_slug=app_slug)
    return addons.views.extension_detail(request, webapp)


def share(request, app_slug):
    webapp = get_object_or_404(Webapp, app_slug=app_slug)
    return share_redirect(request, webapp, webapp.name, webapp.summary)
