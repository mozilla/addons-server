from django.shortcuts import get_object_or_404

import jingo
from tower import ugettext_lazy as _lazy

import amo
from amo.decorators import json_view, login_required, post_required
from amo.utils import paginate
from addons.decorators import addon_view
import addons.views
import search.views

from addons.models import Category
from browse.views import category_landing, CategoryLandingFilter
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

    opts = (('downloads', _lazy(u'Most Popular')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Recently Added')),
            ('featured', _lazy(u'Featured')))


class AppFilter(addons.views.BaseFilter):
    opts = (('downloads', _lazy(u'Weekly Downloads')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Newest')))
    extras = (('name', _lazy(u'Name')),
              ('featured', _lazy(u'Featured')),
              ('updated', _lazy(u'Recently Updated')),
              ('hotness', _lazy(u'Up & Coming')))


def app_listing(request):
    qs = Webapp.objects.listed()
    filter = AppFilter(request, qs, 'sort', default='downloads', model=Webapp)
    return filter.qs, filter


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

    addons, filter = app_listing(request)
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


@json_view
@addon_view
@login_required
@post_required
def record(request, addon):
    if not request.amo_user.installed_set.filter(addon=addon).exists():
        request.amo_user.installed_set.create(addon=addon)
    return {'addon': addon.pk}
