import json
import random
import uuid
import zipfile

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.forms import ValidationError
from django.utils.translation import ugettext

from olympia import amo
from olympia.lib.cache import memoize, memoize_key
from olympia.amo.utils import normalize_string
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.discovery.utils import call_recommendation_server
from olympia.translations.fields import LocaleErrorMessage


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def clear_get_featured_ids_cache(*args, **kwargs):
    cache_key = memoize_key('addons:featured', *args, **kwargs)
    cache.delete(cache_key)


@memoize('addons:featured', timeout=60 * 10)
def get_featured_ids(app=None, lang=None, type=None, types=None):
    from olympia.addons.models import Addon
    ids = []
    is_featured = Q(collections__featuredcollection__isnull=False)
    if app:
        is_featured &= Q(collections__featuredcollection__application=app.id)
    qs = Addon.objects.valid()

    if type:
        qs = qs.filter(type=type)
    elif types:
        qs = qs.filter(type__in=types)
    if lang:
        has_locale = qs.filter(
            is_featured &
            Q(collections__featuredcollection__locale__iexact=lang))
        if has_locale.exists():
            ids += list(has_locale.distinct().values_list('id', flat=True))
        none_qs = qs.filter(
            is_featured &
            Q(collections__featuredcollection__locale__isnull=True))
        blank_qs = qs.filter(is_featured &
                             Q(collections__featuredcollection__locale=''))
        qs = none_qs | blank_qs
    else:
        qs = qs.filter(is_featured)
    other_ids = list(qs.distinct().values_list('id', flat=True))
    random.shuffle(ids)
    random.shuffle(other_ids)
    ids += other_ids
    return map(int, ids)


@memoize('addons:creatured', timeout=60 * 10)
def get_creatured_ids(category, lang=None):
    from olympia.addons.models import Addon
    from olympia.bandwagon.models import FeaturedCollection
    if lang:
        lang = lang.lower()
    per_locale = set()
    if isinstance(category, int):
        category = CATEGORIES_BY_ID[category]
    app_id = category.application

    others = (Addon.objects.public()
              .filter(
                  Q(collections__featuredcollection__locale__isnull=True) |
                  Q(collections__featuredcollection__locale=''),
                  collections__featuredcollection__isnull=False,
                  collections__featuredcollection__application=app_id,
                  category=category.id)
              .distinct()
              .values_list('id', flat=True))

    if lang is not None and lang != '':
        possible_lang_match = FeaturedCollection.objects.filter(
            locale__icontains=lang,
            application=app_id,
            collection__addons__category=category.id).distinct()
        for fc in possible_lang_match:
            if lang in fc.locale.lower().split(','):
                per_locale.update(
                    fc.collection.addons
                    .filter(category=category.id)
                    .values_list('id', flat=True))

    others = list(others)
    per_locale = list(per_locale)
    random.shuffle(others)
    random.shuffle(per_locale)
    return map(int, filter(None, per_locale + others))


def verify_mozilla_trademark(name, user, form=None):
    skip_trademark_check = (
        user and user.is_authenticated() and user.email and
        user.email.endswith(amo.ALLOWED_TRADEMARK_SUBMITTING_EMAILS))

    def _check(name):
        name = normalize_string(name, strip_puncutation=True).lower()

        for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS:
            violates_trademark = (
                name.count(symbol) > 1 or (
                    name.count(symbol) >= 1 and not
                    name.endswith(' for {}'.format(symbol))))

            if violates_trademark:
                raise forms.ValidationError(ugettext(
                    u'Add-on names cannot contain the Mozilla or '
                    u'Firefox trademarks.'))

    if not skip_trademark_check:
        if not isinstance(name, dict):
            _check(name)
        else:
            for locale, localized_name in name.items():
                try:
                    _check(localized_name)
                except forms.ValidationError as exc:
                    if form is not None:
                        for message in exc.messages:
                            error_message = LocaleErrorMessage(
                                message=message, locale=locale)
                            form.add_error('name', error_message)
                    else:
                        raise
    return name


TAAR_LITE_FALLBACKS = [
    'enhancerforyoutube@maximerf.addons.mozilla.org',  # /enhancer-for-youtube/
    '{2e5ff8c8-32fe-46d0-9fc8-6b8986621f3c}',          # /search_by_image/
    'uBlock0@raymondhill.net',                         # /ublock-origin/
    'newtaboverride@agenedia.com']                     # /new-tab-override/

TAAR_LITE_OUTCOME_REAL_SUCCESS = 'recommended'
TAAR_LITE_OUTCOME_REAL_FAIL = 'recommended_fallback'
TAAR_LITE_OUTCOME_CURATED = 'curated'
TAAR_LITE_FALLBACK_REASON_TIMEOUT = 'timeout'
TAAR_LITE_FALLBACK_REASON_EMPTY = 'no_results'
TAAR_LITE_FALLBACK_REASON_INVALID = 'invalid_results'


def get_addon_recommendations(guid_param, taar_enable):
    guids = None
    fail_reason = None
    if taar_enable:
        guids = call_recommendation_server(
            guid_param, {},
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL)
        outcome = (TAAR_LITE_OUTCOME_REAL_SUCCESS if guids
                   else TAAR_LITE_OUTCOME_REAL_FAIL)
        if not guids:
            fail_reason = (TAAR_LITE_FALLBACK_REASON_EMPTY if guids == []
                           else TAAR_LITE_FALLBACK_REASON_TIMEOUT)
    else:
        outcome = TAAR_LITE_OUTCOME_CURATED
    if not guids:
        guids = TAAR_LITE_FALLBACKS
    return guids, outcome, fail_reason


def is_outcome_recommended(outcome):
    return outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS


def get_addon_recommendations_invalid():
    return (
        TAAR_LITE_FALLBACKS, TAAR_LITE_OUTCOME_REAL_FAIL,
        TAAR_LITE_FALLBACK_REASON_INVALID)


def build_static_theme_xpi_from_lwt(lwt, upload_zip):
    # create manifest
    accentcolor = (('#%s' % lwt.persona.accentcolor) if lwt.persona.accentcolor
                   else amo.THEME_ACCENTCOLOR_DEFAULT)
    textcolor = '#%s' % (lwt.persona.textcolor or '000')
    manifest = {
        "manifest_version": 2,
        "name": unicode(lwt.name or lwt.slug),
        "version": '1.0',
        "theme": {
            "images": {
                "headerURL": lwt.persona.header
            },
            "colors": {
                "accentcolor": accentcolor,
                "textcolor": textcolor
            }
        }
    }
    if lwt.description:
        manifest['description'] = unicode(lwt.description)

    # build zip with manifest and background file
    with zipfile.ZipFile(upload_zip, 'w', zipfile.ZIP_DEFLATED) as dest:
        dest.writestr('manifest.json', json.dumps(manifest))
        dest.write(lwt.persona.header_path, arcname=lwt.persona.header)


def build_webext_dictionary_from_legacy(addon, destination):
    """Create a webext package of a legacy dictionary `addon`, and put it in
    `destination` path."""
    from olympia.files.utils import SafeZip  # Avoid circular import.
    old_path = addon.current_version.all_files[0].file_path
    old_zip = SafeZip(old_path)
    if not old_zip.is_valid():
        raise ValidationError('Current dictionary xpi is not valid')

    if not addon.target_locale:
        raise ValidationError('Addon has no target_locale')

    dictionary_path = ''

    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as new_zip:
        for obj in old_zip.filelist:
            splitted = obj.filename.split('/')
            # Ignore useless directories and files.
            if splitted[0] in ('META-INF', '__MACOSX', 'chrome',
                               'chrome.manifest', 'install.rdf'):
                continue

            # Also ignore javascript (regardless of where they are, not just at
            # the root), since dictionaries should not contain any code.
            if splitted[-1].endswith('.js'):
                continue

            # Store the path of the last .dic file we find. It can be inside a
            # directory.
            if (splitted[-1].endswith('.dic')):
                dictionary_path = obj.filename

            new_zip.writestr(obj.filename, old_zip.read(obj.filename))

        # Now that all files we want from the old zip are copied, build and
        # add manifest.json.
        if not dictionary_path:
            # This should not happen... It likely means it's an invalid
            # dictionary to begin with, or one that has its .dic file in a
            # chrome/ directory for some reason. Abort!
            raise ValidationError('Current dictionary xpi has no .dic file')

        # Dumb version number increment. This will be invalid in some cases,
        # but some of the dictionaries we have currently already have wild
        # version numbers anyway.
        version_number = addon.current_version.version
        if version_number.endswith('.1-typefix'):
            version_number = version_number.replace('.1-typefix', '.2webext')
        else:
            version_number = '%s.1webext' % version_number

        manifest = {
            'manifest_version': 2,
            'name': unicode(addon.name),
            'version': version_number,
            'dictionaries': {addon.target_locale: dictionary_path},
        }

        # Write manifest.json we just build.
        new_zip.writestr('manifest.json', json.dumps(manifest))
