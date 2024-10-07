import uuid

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils.translation import gettext

import waffle
from django_statsd.clients import statsd
from rest_framework import status
from rest_framework.response import Response

from olympia import amo, core
from olympia.access.acl import action_allowed_for
from olympia.amo.utils import normalize_string, verify_condition_with_locales
from olympia.discovery.utils import call_recommendation_server
from olympia.translations.models import Translation


log = core.logger.getLogger('z.addons')


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def verify_mozilla_trademark(name, user, *, form=None):
    skip_trademark_check = (
        user
        and user.is_authenticated
        and action_allowed_for(user, amo.permissions.TRADEMARK_BYPASS)
    )

    def _check(name):
        name = normalize_string(name, strip_punctuation=True).lower()

        for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS:
            violates_trademark = name.count(symbol) > 1 or (
                name.count(symbol) >= 1 and not name.endswith(f' for {symbol}')
            )

            if violates_trademark:
                raise forms.ValidationError(
                    gettext(
                        'Add-on names cannot contain the Mozilla or '
                        'Firefox trademarks.'
                    )
                )

    if not skip_trademark_check:
        verify_condition_with_locales(
            value=name, check_func=_check, form=form, field_name='name'
        )

    return name


TAAR_LITE_FALLBACKS = [
    'addon@darkreader.org',  # Dark Reader
    'treestyletab@piro.sakura.ne.jp',  # Tree Style Tab
    'languagetool-webextension@languagetool.org',  # LanguageTool
    '{2e5ff8c8-32fe-46d0-9fc8-6b8986621f3c}',  # Search by Image
]

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
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, guid_param, {}
        )
        if guids:
            outcome = TAAR_LITE_OUTCOME_REAL_SUCCESS
            taar_lite_outcome = 'success'
        else:
            outcome = TAAR_LITE_OUTCOME_REAL_FAIL
            fail_reason = (
                TAAR_LITE_FALLBACK_REASON_EMPTY
                if guids == []
                else TAAR_LITE_FALLBACK_REASON_TIMEOUT
            )
            taar_lite_outcome = fail_reason
        statsd.incr(f'services.addon_recommendations.{taar_lite_outcome}')
    else:
        outcome = TAAR_LITE_OUTCOME_CURATED
    if not guids:
        guids = TAAR_LITE_FALLBACKS
    return guids, outcome, fail_reason


def is_outcome_recommended(outcome):
    return outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS


def get_addon_recommendations_invalid():
    return (
        TAAR_LITE_FALLBACKS,
        TAAR_LITE_OUTCOME_REAL_FAIL,
        TAAR_LITE_FALLBACK_REASON_INVALID,
    )


def compute_last_updated(addon):
    """Compute the value of last_updated for a single add-on."""
    from olympia.addons.models import Addon

    queries = Addon._last_updated_queries()
    if addon.status == amo.STATUS_APPROVED:
        q = 'public'
    else:
        q = 'exp'
    values = (
        queries[q]
        .filter(pk=addon.pk)
        .using('default')
        .values_list('last_updated', flat=True)
    )
    return values[0] if values else None


def fetch_translations_from_addon(addon, properties):
    translation_ids_gen = (getattr(addon, prop + '_id', None) for prop in properties)
    translation_ids = [id_ for id_ in translation_ids_gen if id_]
    # Just get all the values together to make it simplier
    return {str(value) for value in Translation.objects.filter(id__in=translation_ids)}


class DeleteTokenSigner(TimestampSigner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{'salt': 'addon-delete', **kwargs})

    def generate(self, addon_id):
        return self.sign_object({'addon_id': addon_id})

    def validate(self, token, addon_id):
        try:
            token_payload = self.unsign_object(token, max_age=60)
        except (SignatureExpired, BadSignature) as exc:
            log.debug(exc)
            return False
        return token_payload['addon_id'] == addon_id


def validate_version_number_is_gt_latest_signed_listed_version(addon, version_string):
    """Returns an error string if `version_string` isn't greater than the current
    approved listed version. Doesn't apply to langpacks."""
    if (
        addon
        and addon.type != amo.ADDON_LPAPP
        and (
            latest_version_string := addon.versions(manager='unfiltered_for_relations')
            .filter(channel=amo.CHANNEL_LISTED, file__is_signed=True)
            .order_by('created')
            .values_list('version', flat=True)
            .last()
        )
        and latest_version_string >= version_string
    ):
        msg = gettext(
            'Version {version_string} must be greater than the previous approved '
            'version {previous_version_string}.'
        )
        return msg.format(
            version_string=version_string,
            previous_version_string=latest_version_string,
        )


def remove_icons(addon):
    for size in amo.ADDON_ICON_SIZES + ('original',):
        filepath = addon.get_icon_path(size)
        if storage.exists(filepath):
            storage.delete(filepath)


def submissions_disabled_response():
    flag = waffle.get_waffle_flag_model().get('enable-submissions')
    reason = flag.note if hasattr(flag, 'note') else None
    return Response(
        {
            'error': gettext('Submissions are not currently available.'),
            'reason': reason,
        },
        status=status.HTTP_403_FORBIDDEN,
    )
