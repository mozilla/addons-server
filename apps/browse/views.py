import collections

from django import http
from django.conf import settings
from django.http import (Http404, HttpResponsePermanentRedirect,
                         HttpResponseRedirect)
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import cache_page

import jingo
from product_details import product_details
from mobility.decorators import mobile_template
from tower import ugettext_lazy as _lazy

import amo
import amo.models
from amo.models import manual_order
from amo.urlresolvers import reverse
from addons.models import Addon, AddonCategory, Category, FrozenAddon
from addons.utils import get_featured_ids, get_creatured_ids
from addons.views import BaseFilter, ESBaseFilter
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


class AddonFilter(BaseFilter):
    opts = (('featured', _lazy(u'Featured')),
            ('users', _lazy(u'Most Users')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Newest')))
    extras = (('name', _lazy(u'Name')),
              ('popular', _lazy(u'Weekly Downloads')),
              ('updated', _lazy(u'Recently Updated')),
              ('hotness', _lazy(u'Up & Coming')))


class ThemeFilter(AddonFilter):
    opts = (('users', _lazy(u'Most Users')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Newest')))
    extras = (('name', _lazy(u'Name')),
              ('featured', _lazy(u'Featured')),
              ('popular', _lazy(u'Weekly Downloads')),
              ('updated', _lazy(u'Recently Updated')),
              ('hotness', _lazy(u'Up & Coming')))


class ESAddonFilter(ESBaseFilter):
    opts = AddonFilter.opts
    extras = AddonFilter.extras


def addon_listing(request, addon_types, filter_=AddonFilter,
                  default='featured'):
    # Set up the queryset and filtering for themes & extension listing pages.
    qs = (Addon.objects.listed(request.APP, *amo.REVIEWED_STATUSES)
          .filter(type__in=addon_types))
    filter = filter_(request, qs, 'sort', default)
    return filter.qs, filter


def _get_locales(addons):
    """Does the heavy lifting for language_tools."""
    # This is a generator so we can {% cache addons %} in the template without
    # running any of this code.
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

    # We don't need the whole add-on so only store the parts in use.
    def slim(addon):
        return {'slug': addon.slug,
                'file_size': addon.current_version.all_files[0].size,
                'locale_disambiguation': addon.locale_disambiguation}

    locales = {}
    for locale, addons in amo.utils.sorted_groupby(addons, 'target_locale'):
        addons = list(addons)
        dicts = [slim(a) for a in addons if a.type == amo.ADDON_DICT]
        packs = [slim(a) for a in addons if a.type == amo.ADDON_LPAPP]
        addon = addons[0]
        locales[locale] = Locale(addon.target_locale, addon.locale_display,
                                 addon.locale_native, dicts, packs)

    for locale in sorted(locales.items(), key=lambda x: x[1].display):
        yield locale


# We never use the category, but this makes it
# uniform with the other type listings.
def language_tools(request, category=None):
    types = (amo.ADDON_DICT, amo.ADDON_LPAPP)
    addons = (Addon.objects.public()
              .filter(appsupport__app=request.APP.id, type__in=types,
                      target_locale__isnull=False).exclude(target_locale=''))
    locales = _get_locales(addons)
    lang_addons = _get_locales(addons.filter(target_locale=request.LANG))
    addon_ids = addons.values_list('pk', flat=True)
    return jingo.render(request, 'browse/language_tools.html',
                        {'locales': list(locales),
                         #pass keys separately so only IDs get cached
                         'addons': addon_ids,
                         'lang_addons': list(lang_addons),
                         'search_cat': '%s,0' % amo.ADDON_DICT})


def themes(request, category=None):
    TYPE = amo.ADDON_THEME
    if category is not None:
        q = Category.objects.filter(type=TYPE)
        category = get_object_or_404(q, slug=category)

    addons, filter = addon_listing(request, [TYPE], default='users',
                                   filter_=ThemeFilter)
    sorting = filter.field
    src = 'cb-btn-%s' % sorting
    dl_src = 'cb-dl-%s' % sorting

    if category is not None:
        addons = addons.filter(categories__id=category.id)

    addons = amo.utils.paginate(request, addons, 16, count=addons.count())
    return jingo.render(request, 'browse/themes.html',
                {'section': 'themes', 'addon_type': TYPE, 'addons': addons,
                 'category': category, 'filter': filter, 'sorting': sorting,
                 'search_cat': '%s,0' % TYPE, 'src': src, 'dl_src': dl_src})


@mobile_template('browse/{mobile/}extensions.html')
def extensions(request, category=None, template=None):
    TYPE = amo.ADDON_EXTENSION

    if category is not None:
        q = Category.objects.filter(application=request.APP.id, type=TYPE)
        category = get_object_or_404(q, slug=category)

    sort = request.GET.get('sort')
    if not sort and not request.MOBILE and category and category.count > 4:
        return category_landing(request, category)

    addons, filter = addon_listing(request, [TYPE])
    sorting = filter.field
    src = 'cb-btn-%s' % sorting
    dl_src = 'cb-dl-%s' % sorting

    if category:
        addons = addons.filter(categories__id=category.id)

    addons = amo.utils.paginate(request, addons, count=addons.count())
    return jingo.render(request, template,
                        {'section': 'extensions', 'addon_type': TYPE,
                         'category': category, 'addons': addons,
                         'filter': filter, 'sorting': sorting,
                         'sort_opts': filter.opts, 'src': src,
                         'dl_src': dl_src, 'search_cat': '%s,0' % TYPE})


@mobile_template('browse/{mobile/}extensions.html')
def es_extensions(request, category=None, template=None):
    TYPE = amo.ADDON_EXTENSION

    if category is not None:
        q = Category.objects.filter(application=request.APP.id, type=TYPE)
        category = get_object_or_404(q, slug=category)

    if ('sort' not in request.GET and not request.MOBILE
        and category and category.count > 4):
        return category_landing(request, category)

    qs = (Addon.search().filter(type=TYPE, app=request.APP.id,
                                is_disabled=False,
                                status__in=amo.REVIEWED_STATUSES))
    filter = ESAddonFilter(request, qs, key='sort', default='popular')
    qs, sorting = filter.qs, filter.field
    src = 'cb-btn-%s' % sorting
    dl_src = 'cb-dl-%s' % sorting

    if category:
        qs = qs.filter(category=category.id)
    addons = amo.utils.paginate(request, qs)

    return jingo.render(request, template,
                        {'section': 'extensions', 'addon_type': TYPE,
                         'category': category, 'addons': addons,
                         'filter': filter, 'sorting': sorting,
                         'sort_opts': filter.opts, 'src': src,
                         'dl_src': dl_src, 'search_cat': '%s,0' % TYPE})


class CategoryLandingFilter(BaseFilter):

    opts = (('featured', _lazy(u'Featured')),
            ('users', _lazy(u'Most Popular')),
            ('rating', _lazy(u'Top Rated')),
            ('created', _lazy(u'Recently Added')))

    def __init__(self, request, base, category, key, default):
        self.category = category
        self.ids = AddonCategory.creatured_random(category, request.LANG)
        super(CategoryLandingFilter, self).__init__(request, base, key,
                                                    default)

    def filter_featured(self):
        # Never fear this will get & with manual order and the base.
        return Addon.objects.all()

    def order_featured(self, filter):
        return manual_order(filter, self.ids, pk_name='addons.id')


def category_landing(request, category, addon_type=amo.ADDON_EXTENSION,
                     Filter=CategoryLandingFilter):
    if addon_type == amo.ADDON_WEBAPP:
        base = (Addon.objects.public()
                .filter(type=amo.ADDON_WEBAPP, categories__id=category.id))
    else:
        base = (Addon.objects.listed(request.APP)
                .exclude(type=amo.ADDON_PERSONA)
                .filter(categories__id=category.id))
    filter = Filter(request, base, category, key='browse', default='featured')
    return jingo.render(request, 'browse/impala/category_landing.html',
                        {'section': amo.ADDON_SLUGS[addon_type],
                         'addon_type': addon_type, 'category': category,
                         'filter': filter, 'sorting': filter.field,
                         'search_cat': '%s,0' % category.type})


def es_category_landing(request, category):
    # TODO: Match CategoryLandingFilter.
    qs = (Addon.search().filter(type=TYPE, app=request.APP.id,
                                is_disabled=False,
                                status__in=amo.REVIEWED_STATUSES))
    filter = ESAddonFilter(request, qs, key='sort', default='popular')
    return jingo.render(request, 'browse/impala/category_landing.html',
                        {'category': category, 'filter': filter,
                         'search_cat': '%s,0' % category.type})


def creatured(request, category):
    TYPE = amo.ADDON_EXTENSION
    q = Category.objects.filter(application=request.APP.id, type=TYPE)
    category = get_object_or_404(q, slug=category)
    ids = AddonCategory.creatured_random(category, request.LANG)
    addons = manual_order(Addon.objects.public(), ids, pk_name='addons.id')
    return jingo.render(request, 'browse/creatured.html',
                        {'addons': addons, 'category': category,
                         'sorting': 'featured'})


class PersonasFilter(BaseFilter):

    opts = (('up-and-coming', _lazy(u'Up & Coming')),
            ('created', _lazy(u'Recently Added')),
            ('popular', _lazy(u'Most Popular')),
            ('rating', _lazy(u'Top Rated')))

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


def personas_listing(request, category_slug=None):
    # Common pieces using by browse and search.
    TYPE = amo.ADDON_PERSONA
    q = Category.objects.filter(type=TYPE)
    categories = order_by_translation(q, 'name')

    frozen = list(FrozenAddon.objects.values_list('addon', flat=True))

    base = (Addon.objects.public().filter(type=TYPE)
                 .exclude(id__in=frozen)
                 .extra(select={'_app': request.APP.id}))

    cat = None
    if category_slug is not None:
        try:
            cat = Category.objects.filter(slug=category_slug, type=TYPE)[0]
        except IndexError:
            # Maybe it's a Complete Theme?
            try:
                cat = Category.objects.filter(slug=category_slug,
                    type=amo.ADDON_THEME)[0]
            except IndexError:
                raise Http404
            else:
                # Hey, it was a Complete Theme.
                url = reverse('browse.themes', args=[cat.slug])
                if 'sort' in request.GET:
                    url = amo.utils.urlparams(url, sort=request.GET['sort'])
                return redirect(url, permanent=not settings.DEBUG)

        base = base.filter(categories__id=cat.id)

    filter = PersonasFilter(request, base, key='sort', default='up-and-coming')
    return categories, filter, base, cat


@mobile_template('browse/personas/{mobile/}')
def personas(request, category=None, template=None):
    listing = personas_listing(request, category)

    # I guess this was a Complete Theme after all.
    if isinstance(listing,
                  (HttpResponsePermanentRedirect, HttpResponseRedirect)):
        return listing

    categories, filter, base, category = listing

    # Pass the count from base instead of letting it come from
    # filter.qs.count() since that would join against personas.
    count = category.count if category else base.count()

    if ('sort' not in request.GET and ((request.MOBILE and not category) or
                                       (not request.MOBILE and count > 4))):
        template += 'category_landing.html'
    else:
        template += 'grid.html'

    addons = amo.utils.paginate(request, filter.qs, 30, count=count)
    if category:
        ids = AddonCategory.creatured_random(category, request.LANG)
        featured = manual_order(base, ids, pk_name="addons.id")
    else:
        ids = Addon.featured_random(request.APP, request.LANG)
        featured = manual_order(base, ids, pk_name="addons.id")

    ctx = {'categories': categories, 'category': category, 'addons': addons,
           'filter': filter, 'sorting': filter.field, 'sort_opts': filter.opts,
           'featured': featured, 'search_cat': 'themes',
           'is_homepage': category is None and 'sort' not in request.GET}
    return jingo.render(request, template, ctx)


def legacy_theme_redirects(request, category=None, category_name=None):
    url = None

    if category_name is not None:
        # This format is for the Complete Themes RSS feed.
        url = reverse('browse.themes.rss', args=[category_name])
    else:
        if not category or category == 'all':
            url = reverse('browse.personas')
        else:
            try:
                # Theme?
                cat = Category.objects.filter(slug=category,
                                              type=amo.ADDON_PERSONA)[0]
            except IndexError:
                pass
            else:
                # Hey, it was a Theme.
                url = reverse('browse.personas', args=[cat.slug])

    if url:
        if 'sort' in request.GET:
            url = amo.utils.urlparams(url, sort=request.GET['sort'])
        return redirect(url, permanent=not settings.DEBUG)
    else:
        raise Http404


def legacy_fulltheme_redirects(request, category=None):
    """Full Themes have already been renamed to Complete Themes!"""
    url = request.get_full_path().replace('/full-themes',
                                          '/complete-themes')
    return redirect(url, permanent=not settings.DEBUG)


@cache_page(60 * 60 * 24 * 365)
def legacy_redirects(request, type_, category=None, sort=None, format=None):
    type_slug = amo.ADDON_SLUGS.get(int(type_), 'extensions')
    if not category or category == 'all':
        url = reverse('browse.%s' % type_slug)
    else:
        cat = get_object_or_404(Category.objects, id=category)
        if format == 'rss':
            url = reverse('browse.%s.rss' % type_slug, args=[cat.slug])
        else:
            url = reverse('browse.%s' % type_slug, args=[cat.slug])
    mapping = {'updated': 'updated', 'newest': 'created', 'name': 'name',
               'weeklydownloads': 'popular', 'averagerating': 'rating'}
    if 'sort' in request.GET and request.GET['sort'] in mapping:
        url += '?sort=%s' % mapping[request.GET['sort']]
    elif sort in mapping:
        url += '?sort=%s' % mapping[sort]
    return HttpResponsePermanentRedirect(url)


class SearchToolsFilter(AddonFilter):
    opts = (('featured', _lazy(u'Featured')),
            ('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))

    def filter_featured(self):
        # Featured search add-ons in all locales:
        APP, LANG = self.request.APP, self.request.LANG
        ids = get_featured_ids(APP, LANG, amo.ADDON_SEARCH)

        try:
            search_cat = Category.objects.get(slug='search-tools',
                                              application=APP.id)
            others = get_creatured_ids(search_cat, LANG)
            ids.extend(o for o in others if o not in ids)
        except Category.DoesNotExist:
            pass

        return manual_order(Addon.objects.valid(), ids, 'addons.id')


class SearchExtensionsFilter(AddonFilter):
    opts = (('popular', _lazy(u'Most Popular')),
            ('created', _lazy(u'Recently Added')),)


def search_tools(request, category=None):
    """View the search tools page.

    The default landing page will show you both featured
    extensions and featured search Add-ons.  However, any
    other type of sorting on this page will not show extensions.

    Since it's uncommon for a category to have
    featured add-ons the default view for a category will land you
    on popular add-ons instead.  Note also that CSS will hide the
    sort-by-featured link.
    """
    APP, TYPE = request.APP, amo.ADDON_SEARCH
    qs = Category.objects.filter(application=APP.id, type=TYPE)
    categories = order_by_translation(qs, 'name')

    types = [TYPE]
    if category:
        # Category pages do not have features.
        # Sort by popular add-ons instead.
        default = 'popular'
    else:
        default = 'featured'
        # When the non-category page is featured, include extensions.
        if request.GET.get('sort', default) == 'featured':
            types.append(amo.ADDON_EXTENSION)

    addons, filter = addon_listing(request, types, SearchToolsFilter, default)

    if category:
        category = get_object_or_404(qs, slug=category)
        addons = addons.filter(categories__id=category.id)

    addons = amo.utils.paginate(request, addons)

    base = (Addon.objects.listed(request.APP, amo.STATUS_PUBLIC)
                         .filter(type=amo.ADDON_EXTENSION))
    sidebar_ext = SearchExtensionsFilter(request, base, 'sort', 'popular')

    return jingo.render(request, 'browse/search_tools.html',
                        {'categories': categories, 'category': category,
                         'addons': addons, 'filter': filter,
                         'search_extensions_filter': sidebar_ext})


def moreinfo_redirect(request):
    try:
        addon_id = int(request.GET.get('id', ''))
        return redirect('discovery.addons.detail', addon_id, permanent=True)
    except ValueError:
        raise http.Http404
