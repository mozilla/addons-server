import collections
import itertools

from django import http
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_page

from tower import ugettext as _, ugettext_lazy as _lazy
import jingo
import product_details

import amo.utils
from addons.models import Addon, Category
from amo.urlresolvers import reverse
from addons.views import BaseFilter
from translations.query import order_by_translation


languages = dict((lang.lower(), val)
                 for lang, val in product_details.languages.items())


def locale_display_name(locale):
    """
    Return (english name, native name) for the locale.

    Raises KeyError if the locale can't be found.
    """
    if not locale:
        raise KeyError

    if locale.lower() in languages:
        v = languages[locale.lower()]
        return v['English'], v['native']
    else:
        # Take out the regional portion and try again.
        hyphen = locale.rfind('-')
        if hyphen == -1:
            raise KeyError
        else:
            return locale_display_name(locale[:hyphen])


Locale = collections.namedtuple('Locale', 'locale display native dicts packs')


# We never use the category, but this makes it
# uniform with the other type listings.
def language_tools(request, category=None):
    types = (amo.ADDON_DICT, amo.ADDON_LPAPP)
    q = (Addon.objects.public().exclude(target_locale='')
         .filter(type__in=types, target_locale__isnull=False))
    addons = [a for a in q.all() if request.APP in a.compatible_apps]

    for addon in addons:
        locale = addon.target_locale.lower()
        try:
            english, native = locale_display_name(locale)
            # Add the locale as a differentiator if we had to strip the
            # regional portion.
            if locale not in languages:
                native = '%s (%s)' % (native, locale)
            addon.locale_display, addon.locale_native = english, native
        except KeyError:
            english = u'%s (%s)' % (addon.name, locale)
            addon.locale_display, addon.locale_native = english, ''

    locales = {}
    for locale, addons in itertools.groupby(addons, lambda x: x.target_locale):
        addons = list(addons)
        dicts = [a for a in addons if a.type == amo.ADDON_DICT]
        packs = [a for a in addons if a.type == amo.ADDON_LPAPP]
        addon = addons[0]
        locales[locale] = Locale(addon.target_locale, addon.locale_display,
                                 addon.locale_native, dicts, packs)

    locales = sorted(locales.items(), key=lambda x: x[1].display)

    search_cat = '%s,0' % amo.ADDON_DICT

    return jingo.render(request, 'browse/language_tools.html',
                        {'locales': locales, 'search_cat': search_cat})


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


def themes(request, category=None):
    q = Category.objects.filter(application=request.APP.id,
                                type=amo.ADDON_THEME)
    categories = order_by_translation(q, 'name')

    addons, filter, unreviewed = _listing(request, amo.ADDON_THEME)
    total_count = addons.count()

    if category is not None:
        try:
            category = dict((c.slug, c) for c in categories)[category]
        except KeyError:
            raise http.Http404()
        addons = addons.filter(categories__id=category.id)

    themes = amo.utils.paginate(request, addons)

    # Pre-selected category for search form
    search_cat = '%s,0' % amo.ADDON_THEME

    return jingo.render(request, 'browse/themes.html',
                        {'categories': categories, 'total_count': total_count,
                         'themes': themes, 'category': category,
                         'sorting': filter.field,
                         'sort_opts': filter.opts,
                         'unreviewed': unreviewed,
                         'search_cat': search_cat})


def _listing(request, addon_type, default='popular'):
    # Set up the queryset and filtering for themes & extension listing pages.
    status = [amo.STATUS_PUBLIC]

    unreviewed = 'on' if request.GET.get('unreviewed', False) else None
    if unreviewed:
        status.append(amo.STATUS_UNREVIEWED)

    qs = Addon.objects.listed(request.APP, *status).filter(type=addon_type)
    filter = AddonFilter(request, qs, 'sort', default)
    return filter.qs, filter, unreviewed


def extensions(request, category=None):
    TYPE = amo.ADDON_EXTENSION

    if category is not None:
        q = Category.objects.filter(application=request.APP.id, type=TYPE)
        category = get_object_or_404(q, slug=category)

    if 'sort' not in request.GET and category:
        return category_landing(request, category)

    addons, filter, unreviewed = _listing(request, TYPE)

    if category:
        addons = addons.filter(categories__id=category.id)

    count = addons.with_index(addons='type_status_inactive_idx').count()
    addons = amo.utils.paginate(request, addons, count=count)

    search_cat = '%s,%s' % (TYPE, category.id if category else 0)

    return jingo.render(request, 'browse/extensions.html',
                        {'category': category, 'addons': addons,
                         'unreviewed': unreviewed,
                         'sorting': filter.field,
                         'sort_opts': filter.opts,
                         'search_cat': search_cat})


class CategoryLandingFilter(BaseFilter):

    opts = (('featured', _lazy('Featured')),
            ('created', _lazy('Recently Added')),
            ('popular', _lazy('Top Downloads')),
            ('rating', _lazy('Top Rated')))

    def __init__(self, request, base, category, key, default):
        self.category = category
        super(CategoryLandingFilter, self).__init__(request, base, key,
                                                    default)

    def filter_featured(self):
        return Addon.objects.filter(addoncategory__feature=True,
                                    addoncategory__category=self.category)


def category_landing(request, category):
    base = (Addon.objects.listed(request.APP).exclude(type=amo.ADDON_PERSONA)
            .filter(categories__id=category.id))
    filter = CategoryLandingFilter(request, base, category,
                                   key='browse', default='featured')

    search_cat = '%s,%s' % (category.type, category.id)

    return jingo.render(request, 'browse/category_landing.html',
                        {'category': category, 'filter': filter,
                         'search_cat': search_cat})


def creatured(request, category):
    TYPE = amo.ADDON_EXTENSION
    q = Category.objects.filter(application=request.APP.id, type=TYPE)
    category = get_object_or_404(q, slug=category)
    addons = Addon.objects.public().filter(addoncategory__feature=True,
                                           addoncategory__category=category)
    return jingo.render(request, 'browse/creatured.html',
                        {'addons': addons, 'category': category})


class PersonasFilter(BaseFilter):

    opts = (('up-and-coming', _lazy('Up & Coming')),
            ('created', _lazy('Recently Added')),
            ('popular', _lazy('Most Popular')))

    def _filter(self, field):
        qs = Addon.objects
        if field == 'created':
            return (qs.order_by('-created')
                    .with_index(addons='created_type_idx'))
        elif field == 'popular':
            return (qs.order_by('-persona__popularity')
                    .with_index(personas='personas_popularity_idx'))
        elif field == 'rating':
            return (qs.order_by('-bayesian_rating')
                    .with_index(addons='rating_type_idx'))
        else:
            return (qs.order_by('-persona__movers')
                    .with_index(personas='personas_movers_idx'))


def personas(request, category=None):
    TYPE = amo.ADDON_PERSONA
    q = Category.objects.filter(application=request.APP.id,
                                type=TYPE)
    categories = order_by_translation(q, 'name')

    base = Addon.objects.public().filter(type=TYPE)
    featured = base & Addon.objects.featured(request.APP)
    is_homepage = category is None and 'sort' not in request.GET

    if category is not None:
        category = get_object_or_404(q, slug=category)
        base = base.filter(categories__id=category.id)

    filter = PersonasFilter(request, base, key='sort', default='up-and-coming')

    if 'sort' in request.GET:
        template = 'grid.html'
    else:
        template = 'category_landing.html'

    if category:
        count = category.count
    else:
        # Pass the count from base instead of letting it come from
        # filter.qs.count() since that would join against personas.
        count = base.with_index(addons='type_status_inactive_idx').count()
    addons = amo.utils.paginate(request, filter.qs, 30, count=count)

    search_cat = '%s,%s' % (TYPE, category.id if category else 0)

    return jingo.render(request, 'browse/personas/' + template,
                        {'categories': categories, 'category': category,
                         'filter': filter, 'addons': addons,
                         'featured': featured, 'is_homepage': is_homepage,
                         'search_cat': search_cat})


def search_engines(request, category=None):
    return HttpResponse("Search providers browse page stub.")


@cache_page(60 * 60 * 24 * 365)
def legacy_redirects(request, type_, category=None):
    type_slug = amo.ADDON_SLUGS.get(int(type_), 'extensions')
    if not category or category == 'all':
        url = reverse('browse.%s' % type_slug)
    else:
        cat = get_object_or_404(Category.objects, id=category)
        url = reverse('browse.%s' % type_slug, args=[cat.slug])
    mapping = {'updated': 'updated', 'newest': 'created', 'name': 'name',
                'weeklydownloads': 'popular', 'averagerating': 'rating'}
    if 'sort' in request.GET and request.GET['sort'] in mapping:
        url += '?sort=%s' % mapping[request.GET['sort']]
    return HttpResponsePermanentRedirect(url)
