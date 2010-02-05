import collections
import itertools

import jingo
import product_details

import amo
from addons.models import Addon


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
    q = (Addon.objects.public().filter(type__in=types)
         .exclude(target_locale=''))
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
