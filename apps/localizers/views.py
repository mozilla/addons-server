from django import http
from django.conf import settings
from django.shortcuts import redirect
from django.utils import translation

import commonware.log
import jingo
from product_details import product_details

import amo
from access.models import Group
from addons.models import Category
from amo.decorators import json_view, login_required, post_required, write
from amo.urlresolvers import reverse

from .decorators import locale_switcher, valid_locale
from .forms import CategoryFormSet
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


@locale_switcher
@valid_locale
@login_required
def categories(request, locale_code):
    if not _permission_to_edit_locale(request, locale_code):
        return http.HttpResponseForbidden()

    translation.activate('en-US')
    categories_en = dict([(c.id, c) for c in Category.objects.all()])

    translation.activate(locale_code)
    categories_qs = Category.objects.values('id', 'name', 'application')

    formset = CategoryFormSet(request.POST or None, initial=categories_qs)

    # Build a map from category.id to form in formset for precise form display.
    form_map = dict((form.initial['id'], form) for form in formset.forms)

    if request.method == 'POST' and formset.is_valid():
        for form in formset:
            pk = form.cleaned_data.get('id')
            cat = categories_en.get(pk)
            if not cat:
                continue

            cat.name = {locale_code: form.cleaned_data.get('name')}
            cat.save()

        return redirect(reverse('localizers.categories',
                                kwargs=dict(locale_code=locale_code)))

    data = {
        'locale_code': locale_code,
        'userlang': product_details.languages[locale_code],
        'categories_en': categories_en,
        'categories': categories_qs,
        'formset': formset,
        'form_map': form_map,
        'apps': amo.APP_IDS,
        'types': amo.ADDON_TYPE,
    }

    return jingo.render(request, 'localizers/categories.html', data)
