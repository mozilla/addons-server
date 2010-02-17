from django import http
from django.conf import settings

import commonware.log
import jingo
from product_details import product_details

from access.models import Group
from amo.decorators import json_view, login_required, post_required, write
from amo.urlresolvers import reverse

from .helpers import _permission_to_edit_locale
from .models import L10nSettings

log = commonware.log.getLogger('z.l10n')

@write
@login_required
@post_required
@json_view
def set_motd(request):
    """AJAX: Set announcements for either global or per-locale dashboards."""
    lang = request.POST.get('lang')
    msg = request.POST.get('msg')

    if (lang != '' and lang not in settings.AMO_LANGUAGES and
        lang not in settings.HIDDEN_LANGUAGES or msg is None):
        return json_view.error(_('An error occurred saving this message.'))

    if _permission_to_edit_locale(lang):
        return json_view.error(_('Access Denied'))

    l10n_set, created = L10nSettings.objects.get_or_create(locale=lang)

    # MOTDs are monolingual, so always store them in the default fallback
    # locale (probably en-US)
    l10n_set.motd = {settings.LANGUAGE_CODE: msg}
    l10n_set.save(force_update=True)

    log.info("Changing MOTD for (%s) to (%s)", lang or 'global', msg)

    data = {
        'msg': l10n_set.motd.localized_string,
        'msg_purified': unicode(l10n_set.motd)
    }

    return data

def summary(request):
    """global L10n dashboard"""

    data = {
        'languages': product_details.languages,
        'amo_languages': sorted(settings.AMO_LANGUAGES +
                                settings.HIDDEN_LANGUAGES),
        'hidden_languages': settings.HIDDEN_LANGUAGES,
    }

    return jingo.render(request, 'localizers/summary.html', data)


def locale_switcher(f):
    """Decorator redirecting clicks on the locale switcher dropdown."""
    def decorated(request, *args, **kwargs):
        new_userlang = request.GET.get('userlang')
        if (new_userlang and new_userlang in settings.AMO_LANGUAGES or
            new_userlang in settings.HIDDEN_LANGUAGES):
            kwargs['locale_code'] = new_userlang
            return http.HttpResponsePermanentRedirect(reverse(
                decorated, args=args, kwargs=kwargs))
        else:
            return f(request, *args, **kwargs)
    return decorated


def valid_locale(f):
    """Decorator validating locale code for per-language pages."""
    def decorated(request, locale_code, *args, **kwargs):
        if locale_code not in (settings.AMO_LANGUAGES +
                               settings.HIDDEN_LANGUAGES):
            raise http.Http404
        return f(request, locale_code, *args, **kwargs)
    return decorated


@locale_switcher
@valid_locale
def locale_dashboard(request, locale_code):
    """per-locale dashboard"""
    data = {
        'locale_code': locale_code,
        'userlang': product_details.languages[locale_code],
    }

    # group members
    try:
        group = Group.objects.get(
            rules__startswith=('Localizers:%s' % locale_code))
        members = group.users.all()
    except Group.DoesNotExist:
        members = None
    data['members'] = members

    # team homepage
    try:
        l10n_set = L10nSettings.objects.get(locale=locale_code)
        team_homepage = l10n_set.team_homepage
    except L10nSettings.DoesNotExist:
        team_homepage = None
    data['team_homepage'] = team_homepage

    return jingo.render(request, 'localizers/dashboard.html', data)


@login_required
@locale_switcher
@valid_locale
def categories(request, locale_code):
    if _permission_to_edit_locale(request, locale_code):
        return http.HttpResponseForbidden()

    data = {
        'locale_code': locale_code,
        'userlang': product_details.languages[locale_code],
    }

    return jingo.render(request, 'localizers/categories.html', data)
