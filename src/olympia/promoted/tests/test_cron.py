from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.constants.promoted import NOTABLE, NOT_PROMOTED
from olympia.promoted.models import PromotedAddon
from olympia.zadmin.models import set_config

from ..cron import add_high_adu_extensions_to_notable, ADU_LIMIT_CONFIG_KEY


def test_add_high_adu_extensions_to_notable():
    # Arbitrary_adu_limit
    adu_limit = 1234
    set_config(ADU_LIMIT_CONFIG_KEY, adu_limit)

    extension_with_low_adu = addon_factory(average_daily_users=adu_limit - 1)
    extension_with_high_adu = addon_factory(average_daily_users=adu_limit)
    ignored_theme = addon_factory(
        average_daily_users=adu_limit + 1, type=amo.ADDON_STATICTHEME
    )
    already_promoted_extension = addon_factory(average_daily_users=adu_limit + 1)
    PromotedAddon.objects.create(addon=already_promoted_extension)

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
    assert (
        already_promoted_extension.reload().promoted_group(currently_approved=False)
        == NOT_PROMOTED
    )

    assert extension_with_high_adu.current_version.needs_human_review
