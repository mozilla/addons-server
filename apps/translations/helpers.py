from django.conf import settings
from django.utils import translation

import jinja2

from jingo import register


@register.filter
def locale_html(translatedfield):
    """HTML attributes for languages different than the site language"""
    sitelang = translation.get_language()
    sitelocale = translation.to_locale(sitelang)
    locale = translation.to_locale(translatedfield.locale)
    if locale == sitelocale:
        return ''
    else:
        textdir = 'rtl' if locale in settings.RTL_LANGUAGES else 'ltr'
        return jinja2.Markup(' lang="%s" dir="%s"' % (translatedfield.locale,
                                                      textdir))
