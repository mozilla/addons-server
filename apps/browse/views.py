import collections
import itertools

from l10n import ugettext as _, ugettext_lazy as _lazy

import jingo
import product_details

import amo.utils
from addons.models import Addon, Category
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


class AddonSorter(object):
    """
    Support class for sorting add-ons.  Sortable fields are defined as
    (value, title) pairs in ``opts``.  Pass in a request and a queryset and
    AddonSorter will figure out how to sort the queryset.

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
    APP, THEME = request.APP, amo.ADDON_THEME
    status = [amo.STATUS_PUBLIC]

    experimental = 'on' if request.GET.get('experimental', False) else None
    if experimental:
        status.append(amo.STATUS_SANDBOX)

    q = Category.objects.filter(application=APP.id, type=THEME)
    categories = order_by_translation(q, 'name')

    addons = Addon.objects.listed(APP, *status).filter(type=THEME).distinct()
    total_count = addons.count()

    sorting, sort_opts, addons = AddonSorter(request, addons, 'downloads')

    if category is None:
        selected = _Category(_('All'), total_count, '')
    else:
        selected = dict((c.slug, c) for c in categories)[category]
        addons = addons.filter(categories__slug=category)

    themes = amo.utils.paginate(request, addons)

    return jingo.render(request, 'browse/themes.html',
                        {'categories': categories, 'total_count': total_count,
                         'themes': themes, 'selected': selected,
                         'sorting': sorting, 'sort_opts': sort_opts,
                         'experimental': experimental})
