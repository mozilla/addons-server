import json
import os.path
import re
import uuid
import zipfile

from django import forms
from django.conf import settings
from django.forms import ValidationError
from django.utils.translation import ugettext

from olympia import amo
from olympia.amo.utils import normalize_string, to_language
from olympia.discovery.utils import call_recommendation_server
from olympia.translations.fields import LocaleErrorMessage


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def verify_mozilla_trademark(name, user, form=None):
    skip_trademark_check = (
        user and user.is_authenticated and user.email and
        user.email.endswith(amo.ALLOWED_TRADEMARK_SUBMITTING_EMAILS))

    def _check(name):
        name = normalize_string(name, strip_punctuation=True).lower()

        for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS:
            if symbol in name:
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
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, guid_param, {})
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


MULTIPLE_STOPS_REGEX = re.compile(r'\.{2,}')


def build_webext_dictionary_from_legacy(addon, destination):
    """Create a webext package of a legacy dictionary `addon`, and put it in
    `destination` path."""
    from olympia.files.utils import SafeZip  # Avoid circular import.
    old_path = addon.current_version.all_files[0].file_path
    old_zip = SafeZip(old_path)
    if not old_zip.is_valid:
        raise ValidationError('Current dictionary xpi is not valid')

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

        if addon.target_locale:
            target_language = addon.target_locale
        else:
            # Guess target_locale since we don't have one already. Note that
            # for extra confusion, target_locale is a language, not a locale.
            target_language = to_language(os.path.splitext(
                os.path.basename(dictionary_path))[0])
            if target_language not in settings.AMO_LANGUAGES:
                # We couldn't find that language in the list we support. Let's
                # try with just the prefix.
                target_language = target_language.split('-')[0]
                if target_language not in settings.AMO_LANGUAGES:
                    # We tried our best.
                    raise ValidationError(u'Addon has no target_locale and we'
                                          u' could not guess one from the xpi')

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
            'name': str(addon.name),
            'browser_specific_settings': {
                'gecko': {
                    'id': addon.guid,
                },
            },
            'version': version_number,
            'dictionaries': {target_language: dictionary_path},
        }

        # Write manifest.json we just build.
        new_zip.writestr('manifest.json', json.dumps(manifest))
