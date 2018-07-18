from django.conf import settings
from django.template import engines, loader
from django.utils import translation
from django.utils.encoding import force_text
from django.utils.translation.trans_real import to_language

import bleach
import jinja2

from django_jinja import library

from olympia.amo.utils import clean_nl
from olympia.translations.models import PurifiedTranslation


library.filter(to_language)


@library.filter
def locale_html(translatedfield):
    """HTML attributes for languages different than the site language"""
    if not translatedfield:
        return ''

    site_locale = translation.to_locale(translation.get_language())
    locale = translation.to_locale(translatedfield.locale)
    if locale == site_locale:
        return ''
    else:
        rtl_locales = map(translation.to_locale, settings.LANGUAGES_BIDI)
        textdir = 'rtl' if locale in rtl_locales else 'ltr'
        return jinja2.Markup(
            ' lang="%s" dir="%s"'
            % (jinja2.escape(translatedfield.locale), textdir)
        )


@library.filter
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

    return jinja2.filters.do_truncate(
        engines['jinja2'].env, force_text(s), length, killwords, end
    )


@library.global_function
@library.render_with('translations/trans-menu.html')
@jinja2.contextfunction
def l10n_menu(context, default_locale='en-us', remove_locale_url=''):
    """Generates the locale menu for zamboni l10n."""
    default_locale = default_locale.lower()
    languages = dict((i.lower(), j) for i, j in settings.LANGUAGES.items())
    c = dict(context.items())
    if 'addon' in c:
        remove_locale_url = c['addon'].get_dev_url('remove-locale')
    c.update(
        {
            'languages': languages,
            'default_locale': default_locale,
            'remove_locale_url': remove_locale_url,
        }
    )
    return c


@library.filter
def all_locales(addon, field_name, nl2br=False, prettify_empty=False):
    field = getattr(addon, field_name, None)
    if not addon or field is None:
        return
    trans = field.__class__.objects.filter(
        id=field.id, localized_string__isnull=False
    )
    ctx = dict(
        addon=addon,
        field=field,
        field_name=field_name,
        translations=trans,
        nl2br=nl2br,
        prettify_empty=prettify_empty,
    )
    t = loader.get_template('translations/all-locales.html')
    return jinja2.Markup(t.render(ctx))


@library.filter
def clean(string, strip_all_html=False):
    """Clean html with bleach.

    :param string string: The original string to clean.
    :param bool strip_all_html: If given, remove all html code from `string`.
    """
    # Edgecase for PurifiedTranslation to avoid already-escaped html code
    # to slip through. This isn't a problem if `strip_all_html` is `False`.
    if isinstance(string, PurifiedTranslation) and strip_all_html:
        string = string.localized_string

    if hasattr(string, '__html__'):
        string = string.__html__()

    if strip_all_html:
        string = bleach.clean(unicode(string), tags=[], strip=True)
    else:
        string = bleach.clean(unicode(string))

    return jinja2.Markup(clean_nl(string).strip())


@library.filter
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
