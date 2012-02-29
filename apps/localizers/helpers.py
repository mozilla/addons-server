from django.conf import settings

import jinja2
from jingo import register
from product_details import product_details

from access import acl

from .models import L10nSettings


def _permission_to_edit_locale(request, locale=''):
    """If locale is empty, it checks global permissions."""

    if acl.action_allowed(request, 'Locales', 'Edit'):
        return True

    if locale and acl.action_allowed(request, 'Locale.%s' % locale, 'Edit'):
        return True

    return False


@register.inclusion_tag('localizers/sidebar.html')
@jinja2.contextfunction
def localizers_sidebar(context, locale_code=""):
    """Sidebar on the per-locale localizer dashboard page."""
    ctx = dict(context.items())
    request = context['request']

    ctx.update({
        'is_localizer': _permission_to_edit_locale(request, locale_code),
        'locale_code': locale_code,
    })
    return ctx


@register.inclusion_tag('localizers/sidebar_motd.html')
@jinja2.contextfunction
def localizers_sidebar_motd(context, lang=''):
    """Message of the Day on localizer dashboards."""

    request = context['request']

    try:
        l10n_set = L10nSettings.objects.get(locale=lang)
        motd = l10n_set.motd
    except L10nSettings.DoesNotExist:
        motd = None

    ctx = dict(context.items())
    ctx.update({
        'motd_lang': lang,
        'motd': motd,
        'is_localizer': _permission_to_edit_locale(request, lang),
    })
    return ctx


@register.inclusion_tag('localizers/locale_switcher.html')
def locale_switcher(current_locale=None):
    """Locale dropdown to switch user locale on localizer pages."""
    return {
        'current_locale': current_locale,
        'locales': settings.AMO_LANGUAGES + settings.HIDDEN_LANGUAGES,
        'languages': product_details.languages,
    }
