from django.conf import settings
from django.template import engines, loader
from django.utils import translation
from django.utils.encoding import force_str
from django.utils.translation.trans_real import to_language

import jinja2
import markupsafe

from django_jinja import library


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
        return markupsafe.Markup(
            f' lang="{markupsafe.escape(translatedfield.locale)}" dir="{textdir}"'
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
        engines['jinja2'].env, force_str(s), length, killwords, end
    )


@library.global_function
@library.render_with('translations/trans-menu.html')
@jinja2.pass_context
def l10n_menu(context, default_locale='en-us', remove_locale_url=''):
    """Generates the locale menu for zamboni l10n."""
    default_locale = default_locale.lower()
    languages = dict(settings.LANGUAGES)
    ctx = dict(context.items())
    if 'addon' in ctx:
        remove_locale_url = ctx['addon'].get_dev_url('remove-locale')
    ctx.update(
        {
            'languages': languages,
            'default_locale': default_locale,
            'remove_locale_url': remove_locale_url,
        }
    )
    return ctx


@library.filter
def all_locales(addon, field_name, nl2br=False, prettify_empty=False):
    field = getattr(addon, field_name, None)
    if not addon or field is None:
        return
    trans = field.__class__.objects.filter(id=field.id, localized_string__isnull=False)
    ctx = dict(
        addon=addon,
        field=field,
        field_name=field_name,
        translations=trans,
        nl2br=nl2br,
        prettify_empty=prettify_empty,
    )
    t = loader.get_template('translations/all-locales.html')
    return markupsafe.Markup(t.render(ctx))
