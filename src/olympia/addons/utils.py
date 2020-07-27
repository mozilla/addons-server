import uuid

from django import forms
from django.conf import settings
from django.utils.translation import ugettext

from olympia import amo
from olympia.amo.utils import normalize_string
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
