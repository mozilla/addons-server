from itertools import groupby

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

import commonware.log
import jingo
from product_details import product_details

import amo
from access.models import Group
from addons.models import Category
from amo.decorators import json_view, login_required, post_required, write
from amo.urlresolvers import reverse
from amo.utils import no_translation
from translations.models import Translation

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
            rules__startswith=('Locale.%s:' % locale_code))
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
        raise PermissionDenied

    with no_translation():
        cats = list(Category.objects.order_by('application'))

    strings = dict(Translation.objects.filter(
        id__in=[c.name_id for c in cats], locale=locale_code)
        .values_list('id', 'localized_string'))

    # Category ID to localized string map for checking for changes.
    category_names = dict([(c.id, strings.get(c.name_id)) for c in cats])
    # Category ID to model object to avoid extra SQL lookups on POST.
    category_objects = dict([(c.id, c) for c in cats])
    # Initial data to pre-populate forms.
    initial = [dict(id=c.id, name=strings.get(c.name_id),
                    application=c.application_id) for c in cats]
    # Group categories by application, and sort by name within app groups.
    categories = []
    category_no_app = None
    for key, group in groupby(cats, lambda c: c.application_id):
        sorted_cats = sorted(group, key=lambda c: c.name)
        if key:
            categories.append((key, sorted_cats))
        else:
            category_no_app = (key, sorted_cats)
    if category_no_app:  # Put app-less categories at the bottom.
        categories.append(category_no_app)

    formset = CategoryFormSet(request.POST or None, initial=initial)
    # Category ID to form mapping.
    form_map = dict((form.initial['id'], form) for form in formset.forms)

    if request.method == 'POST' and formset.is_valid():
        for form in formset:
            pk = form.cleaned_data.get('id')
            name = form.cleaned_data.get('name')
            if name != category_names.get(pk):
                cat = category_objects.get(pk)
                if not cat:
                    continue
                # The localized string has changed.
                # Make sure we don't save an empty string value.
                if name == '' and category_names.get(pk) == None:
                    # If the form field was left blank and there was no
                    # previous translation, do nothing.
                    continue
                elif name == '' and category_names.get(pk) != None:
                    # If the name is blank and there was a prior translation,
                    # assume they want to remove this translation.
                    #
                    # TODO(robhudson): Figure out how to delete a single
                    # translation properly. Calling...
                    #
                    #   Translation.objects.filter(id=cat.name.id,
                    #                              locale=locale_code).delete()
                    #
                    # ...results in some crazy db traversal that tries to
                    # delete all kinds of things.
                    pass
                else:
                    # Otherwise, name is not empty and it had a prior
                    # translation so update it.
                    cat.name = {locale_code: name}
                    cat.save()

        return redirect(reverse('localizers.categories',
                                kwargs=dict(locale_code=locale_code)))

    data = {
        'locale_code': locale_code,
        'userlang': product_details.languages[locale_code],
        'categories': categories,
        'formset': formset,
        'form_map': form_map,
        'apps': amo.APP_IDS,
        'types': amo.ADDON_TYPE,
    }

    return jingo.render(request, 'localizers/categories.html', data)
