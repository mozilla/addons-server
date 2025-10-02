import uuid
from collections import defaultdict

from django import forms
from django.core.files.storage import default_storage as storage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils.translation import gettext

from olympia import amo, core
from olympia.access.acl import action_allowed_for
from olympia.amo.utils import (
    generate_lowercase_homoglyphs_variants_for_string,
    normalize_string_for_name_checks,
    verify_condition_with_locales,
)
from olympia.translations.models import Translation


log = core.logger.getLogger('z.addons')


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def validate_addon_name(name, user, *, form=None):
    """
    Validate that an add-on name is allowed.

    name can either be  a string or a dict of locale (string) -> name (string)
    items.

    Users with TRADEMARK_BYPASS permission bypass checks performed by this
    function.
    """
    skip_trademark_check = (
        user
        and user.is_authenticated
        and action_allowed_for(user, amo.permissions.TRADEMARK_BYPASS)
    )

    def _check(name):
        name_without_punctuation = normalize_string_for_name_checks(
            name, categories_to_strip=('P')
        ).lower()

        variants = generate_lowercase_homoglyphs_variants_for_string(
            normalize_string_for_name_checks(name)
        )

        for index, variant in enumerate(variants):
            if index > 65535:
                # index > 65535 means over 16 confusable characters with 2
                # variants each. That name is likely suspicious, and it's too
                # expensive to continue anyway. Reject it immediately.
                raise forms.ValidationError(gettext('This name cannot be used.'))

            if skip_trademark_check:
                continue

            for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS:
                symbol_count = variant.count(symbol)
                violates_trademark = symbol_count > 1 or (
                    symbol_count >= 1
                    # 'XXX for Mozilla' or 'XXX for Firefox' is allowed.
                    and not name_without_punctuation.endswith(f' for {symbol}')
                )

                if violates_trademark:
                    msg = gettext(
                        'Add-on names cannot contain the Mozilla or Firefox trademarks.'
                    )
                    raise forms.ValidationError(msg)

    verify_condition_with_locales(
        value=name, check_func=_check, form=form, field_name='name'
    )

    return name


RECOMMENDATIONS = [
    'addon@darkreader.org',  # Dark Reader
    'treestyletab@piro.sakura.ne.jp',  # Tree Style Tab
    'languagetool-webextension@languagetool.org',  # LanguageTool
    '{2e5ff8c8-32fe-46d0-9fc8-6b8986621f3c}',  # Search by Image
    'simple-tab-groups@drive4ik',  # Simple Tab Groups
]

RECOMMENDATION_OUTCOME_CURATED = 'curated'


def get_addon_recommendations(guid_param):
    return get_filtered_fallbacks(guid_param)


def get_filtered_fallbacks(current_guid=None):
    # Filter out the current_guid from RECOMMENDATIONS.
    # A maximum of 4 should be returned at a time.
    # See https://mozilla.github.io/addons-server/topics/api/addons.html#recommendations
    return [guid for guid in RECOMMENDATIONS if guid != current_guid][:4]


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
    translation_ids_gen = (
        (prop, getattr(addon, prop + '_id', None)) for prop in properties
    )
    translation_ids = {id_: prop for prop, id_ in translation_ids_gen if id_}
    # Just get all the values together to make it simplier
    out = defaultdict(set)
    for trans in Translation.objects.filter(id__in=translation_ids):
        out[translation_ids.get(trans.id, '_')].add(str(trans))
    return out


def get_translation_differences(old_, new_):
    out = {}
    for field in list({*old_, *new_}):
        removed = list(old_[field] - new_[field])
        added = list(new_[field] - old_[field])
        if removed or added:
            out[field] = {'removed': removed, 'added': added}
    return out


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


def remove_icons(addon):
    for size in amo.ADDON_ICON_SIZES + ('original',):
        filepath = addon.get_icon_path(size)
        if storage.exists(filepath):
            storage.delete(filepath)
