import collections
import itertools

from django.shortcuts import get_object_or_404

from tower import ugettext as _, ugettext_lazy as _lazy
import jingo
import product_details

import amo.utils
from addons.models import Addon, Category
from addons.views import HomepageFilter
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


def language_tools(request):
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
        dicts = [a for a in addons if a.type_id == amo.ADDON_DICT]
        packs = [a for a in addons if a.type_id == amo.ADDON_LPAPP]
        addon = addons[0]
        locales[locale] = Locale(addon.target_locale, addon.locale_display,
                                 addon.locale_native, dicts, packs)

    locales = sorted(locales.items(), key=lambda x: x[1].display)
    return jingo.render(request, 'browse/language_tools.html',
                        {'locales': locales})

# Placeholder for the All category.
_Category = collections.namedtuple('Category', 'name count slug')


class AddonFilter(object):
    """
    Support class for sorting add-ons.  Sortable fields are defined as
    (value, title) pairs in ``opts``.  Pass in a request and a queryset and
    AddonFilter will figure out how to sort the queryset.

    self.sorting: the field we're sorting by
    self.opts: all the sort options
    self.qs: the sorted queryset
    """
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('downloads', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))

    def __init__(self, request, queryset, default):
        self.sorting = self.options(request, default)
        self.qs = self.sort(queryset, self.sorting)

    def __iter__(self):
        """Cleverness: this lets you unpack the class like a tuple."""
        return iter((self.sorting, self.opts, self.qs))

    def options(self, request, default):
        opts_dict = dict(self.opts)
        if 'sort' in request.GET and request.GET['sort'] in opts_dict:
            sort = request.GET['sort']
            return sort
        else:
            return default

    def sort(self, qs, field):
        if field == 'updated':
            return qs.order_by('-last_updated')
        if field == 'created':
            return qs.order_by('-created')
        elif field == 'downloads':
            return qs.order_by('-weekly_downloads')
        elif field == 'rating':
            return qs.order_by('-bayesian_rating')
        else:
            return order_by_translation(qs, 'name')


def themes(request, category=None):
    q = Category.objects.filter(application=request.APP.id,
                                type=amo.ADDON_THEME)
    categories = order_by_translation(q, 'name')

    addons, filter, unreviewed = _listing(request, amo.ADDON_THEME)
    total_count = addons.count()

    if category is None:
        selected = _Category(_('All'), total_count, '')
    else:
        selected = dict((c.slug, c) for c in categories)[category]
        addons = addons.filter(categories__slug=category)

    themes = amo.utils.paginate(request, addons)

    return jingo.render(request, 'browse/themes.html',
                        {'categories': categories, 'total_count': total_count,
                         'themes': themes, 'selected': selected,
                         'sorting': filter.sorting,
                         'sort_opts': filter.opts,
                         'unreviewed': unreviewed})


def _listing(request, addon_type, default='downloads'):
    # Set up the queryset and filtering for themes & extension listing pages.
    status = [amo.STATUS_PUBLIC]

    unreviewed = 'on' if request.GET.get('unreviewed', False) else None
    if unreviewed:
        status.append(amo.STATUS_UNREVIEWED)

    qs = (Addon.objects.listed(request.APP, *status)
          .filter(type=addon_type).distinct())
    filter = AddonFilter(request, qs, default)
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

    addons = amo.utils.paginate(request, addons)

    return jingo.render(request, 'browse/extensions.html',
                        {'category': category, 'addons': addons,
                         'unreviewed': unreviewed,
                         'sorting': filter.sorting,
                         'sort_opts': filter.opts})


class CategoryLandingFilter(HomepageFilter):

    opts = (('featured', _('Featured')),
            ('created', _('Recently Added')),
            ('downloads', _('Top Downloads')),
            ('rating', _('Top Rated')))

    def __init__(self, request, base, category, key, default):
        self.category = category
        super(CategoryLandingFilter, self).__init__(request, base, key,
                                                    default)

    def _filter(self, field):
        qs = Addon.objects
        if field == 'created':
            return qs.order_by('-created')
        elif field == 'downloads':
            return qs.order_by('-weekly_downloads')
        elif field == 'rating':
            return qs.order_by('-bayesian_rating')
        else:
            return qs.filter(addoncategory__feature=True,
                             addoncategory__category=self.category)


def category_landing(request, category):
    base = (Addon.objects.listed(request.APP).exclude(type=amo.ADDON_PERSONA)
            .filter(categories__id=category.id))
    filter = CategoryLandingFilter(request, base, category,
                                   key='browse', default='featured')

    return jingo.render(request, 'browse/category_landing.html',
                        {'category': category, 'filter': filter})


def creatured(request, category):
    TYPE = amo.ADDON_EXTENSION
    q = Category.objects.filter(application=request.APP.id, type=TYPE)
    category = get_object_or_404(q, slug=category)
    addons = Addon.objects.filter(addoncategory__feature=True,
                                  addoncategory__category=category)
    return jingo.render(request, 'browse/creatured.html',
                        {'addons': addons, 'category': category})


class PersonasFilter(HomepageFilter):

    opts = (('up-and-coming', _('Up & Coming')),
            ('created', _('Recently Added')),
            ('popular', _('Most Popular')),
            ('rating', _('Top Rated')))

    def _filter(self, field):
        qs = Addon.objects
        if field == 'created':
            return qs.order_by('-created')
        elif field == 'popular':
            return qs.order_by('-persona__popularity')
        elif field == 'rating':
            return qs.order_by('-bayesian_rating')
        else:
            return qs.order_by('-persona__movers')


def personas(request, category=None):
    TYPE = amo.ADDON_PERSONA
    q = Category.objects.filter(application=request.APP.id,
                                type=TYPE)
    categories = order_by_translation(q, 'name')

    base = Addon.objects.valid().filter(type=TYPE)

    if category is not None:
        category = get_object_or_404(q, slug=category)
        base = base.filter(categories__id=category.id)

    filter = PersonasFilter(request, base, key='sort', default='up-and-coming')

    if 'sort' in request.GET:
        template = 'grid.html'
    else:
        template = 'category_landing.html'

    addons = amo.utils.paginate(request, filter.qs, 30)
    return jingo.render(request, 'browse/personas/' + template,
                        {'categories': categories, 'category': category,
                         'filter': filter, 'addons': addons})
