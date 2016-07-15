from django.conf import settings
from django.utils import translation
from django.utils.translation.trans_real import to_language
from django.utils.encoding import smart_unicode

import bleach
import jinja2
import jingo

from olympia.amo.utils import clean_nl

jingo.register.filter(to_language)


@jingo.register.filter
def locale_html(translatedfield):
    """HTML attributes for languages different than the site language"""
    if not translatedfield:
        return ''

    site_locale = translation.to_locale(translation.get_language())
    locale = translation.to_locale(translatedfield.locale)
    if locale == site_locale:
        return ''
    else:
        rtl_locales = map(translation.to_locale, settings.RTL_LANGUAGES)
        textdir = 'rtl' if locale in rtl_locales else 'ltr'
        return jinja2.Markup(' lang="%s" dir="%s"' % (
            jinja2.escape(translatedfield.locale), textdir))


@jingo.register.filter
def truncate(s, length=255, killwords=True, end='...'):
    """
    Wrapper for jinja's truncate that checks if the object has a
    __truncate__ attribute first.

    Altering the jinja2 default of killwords=False because of
    https://bugzilla.mozilla.org/show_bug.cgi?id=624642, which could occur
    elsewhere.
    """
    if s is None:
        return ''
    if hasattr(s, '__truncate__'):
        return s.__truncate__(length, killwords, end)
    return jinja2.filters.do_truncate(smart_unicode(s), length, killwords, end)


@jingo.register.inclusion_tag('translations/trans-menu.html')
@jinja2.contextfunction
def l10n_menu(context, default_locale='en-us', remove_locale_url=''):
    """Generates the locale menu for zamboni l10n."""
    default_locale = default_locale.lower()
    languages = dict((i.lower(), j) for i, j in settings.LANGUAGES.items())
    c = dict(context.items())
    if 'addon' in c:
        remove_locale_url = c['addon'].get_dev_url('remove-locale')
    c.update({'languages': languages, 'default_locale': default_locale,
              'remove_locale_url': remove_locale_url})
    return c


@jingo.register.filter
def all_locales(addon, field_name, nl2br=False, prettify_empty=False):
    field = getattr(addon, field_name, None)
    if not addon or field is None:
        return
    trans = field.__class__.objects.filter(id=field.id,
                                           localized_string__isnull=False)
    ctx = dict(addon=addon, field=field, field_name=field_name,
               translations=trans, nl2br=nl2br, prettify_empty=prettify_empty)
    t = jingo.get_env().get_template('translations/all-locales.html')
    return jinja2.Markup(t.render(ctx))


@jingo.register.filter
def clean(string):
    return jinja2.Markup(clean_nl(bleach.clean(unicode(string))).strip())


@jingo.register.filter
def no_links(string):
    """Leave text links untouched, keep only inner text on URLs."""
    if not string:
        return string
    if hasattr(string, '__html__'):
        string = string.__html__()
    allowed_tags = bleach.ALLOWED_TAGS[:]
    allowed_tags.remove('a')
    no_links = bleach.clean(string, tags=allowed_tags, strip=True)
    return jinja2.Markup(clean_nl(no_links).strip())
