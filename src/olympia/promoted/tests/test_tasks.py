import pytest

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.constants.promoted import LINE, NOTABLE, NOT_PROMOTED
from olympia.promoted.models import PromotedAddon
from olympia.zadmin.models import set_config

from ..tasks import add_high_adu_extensions_to_notable, ADU_LIMIT_CONFIG_KEY


@pytest.mark.django_db
def test_add_high_adu_extensions_to_notable():
    # Arbitrary_adu_limit
    adu_limit = 1234
    set_config(ADU_LIMIT_CONFIG_KEY, adu_limit)

    extension_with_low_adu = addon_factory(average_daily_users=adu_limit - 1)
    extension_with_high_adu = addon_factory(average_daily_users=adu_limit)
    ignored_theme = addon_factory(
        average_daily_users=adu_limit + 1, type=amo.ADDON_STATICTHEME
    )
    already_promoted = addon_factory(average_daily_users=adu_limit + 1)
    PromotedAddon.objects.create(addon=already_promoted, group_id=LINE.id)
    promoted_record_exists = addon_factory(average_daily_users=adu_limit + 1)
    PromotedAddon.objects.create(addon=promoted_record_exists, group_id=NOT_PROMOTED.id)

    add_high_adu_extensions_to_notable()

    assert (
        extension_with_low_adu.reload().promoted_group(currently_approved=False)
        == NOT_PROMOTED
    )
    assert (
        extension_with_high_adu.reload().promoted_group(currently_approved=False)
        == NOTABLE
    )
    assert (
        ignored_theme.reload().promoted_group(currently_approved=False) == NOT_PROMOTED
    )
    already_promoted.reload().promotedaddon.reload()
    assert already_promoted.promoted_group(currently_approved=False) == LINE
    promoted_record_exists.reload().promotedaddon.reload()
    assert promoted_record_exists.promoted_group(currently_approved=False) == NOTABLE

    assert extension_with_high_adu.current_version.needs_human_review
    assert promoted_record_exists.current_version.needs_human_review
