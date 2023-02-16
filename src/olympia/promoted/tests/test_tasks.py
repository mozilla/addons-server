from datetime import datetime, timedelta

import pytest

from freezegun import freeze_time

from olympia import amo
from olympia.amo.tests import addon_factory, version_factory
from olympia.constants.promoted import LINE, NOTABLE, NOT_PROMOTED
from olympia.promoted.models import PromotedAddon
from olympia.versions.utils import get_review_due_date
from olympia.zadmin.models import set_config

from ..tasks import (
    add_high_adu_extensions_to_notable,
    ADU_LIMIT_CONFIG_KEY,
    TARGET_PER_DAY_CONFIG_KEY,
)


@pytest.mark.django_db
def test_add_high_adu_extensions_to_notable():
    # Arbitrary_adu_limit
    adu_limit = 1234
    set_config(ADU_LIMIT_CONFIG_KEY, adu_limit)
    # arbitrary target per day
    target_per_day = 12
    set_config(TARGET_PER_DAY_CONFIG_KEY, target_per_day)

    extension_with_low_adu = addon_factory(
        average_daily_users=adu_limit - 1, file_kw={'is_signed': True}
    )
    extension_with_high_adu = addon_factory(
        average_daily_users=adu_limit, file_kw={'is_signed': True}
    )
    ignored_theme = addon_factory(
        average_daily_users=adu_limit + 1, type=amo.ADDON_STATICTHEME
    )
    already_promoted = addon_factory(
        average_daily_users=adu_limit + 1, file_kw={'is_signed': True}
    )
    PromotedAddon.objects.create(addon=already_promoted, group_id=LINE.id)
    promoted_record_exists = addon_factory(
        average_daily_users=adu_limit + 1, file_kw={'is_signed': True}
    )
    PromotedAddon.objects.create(addon=promoted_record_exists, group_id=NOT_PROMOTED.id)
    unlisted_only_extension = addon_factory(
        average_daily_users=adu_limit + 1,
        version_kw={'channel': amo.CHANNEL_UNLISTED},
        file_kw={'is_signed': True},
    )
    mixed_extension = addon_factory(
        average_daily_users=adu_limit + 1, file_kw={'is_signed': True}
    )
    mixed_extension_listed_version = mixed_extension.current_version
    mixed_extension_listed_version.delete()
    mixed_extension_unlisted_version = version_factory(
        addon=mixed_extension, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
    )
    deleted_extension = addon_factory(
        average_daily_users=adu_limit + 1, file_kw={'is_signed': True}
    )
    deleted_extension_version = deleted_extension.current_version
    deleted_extension.delete()

    with freeze_time():
        now = datetime.now()
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
    assert unlisted_only_extension.promoted_group(currently_approved=False) == NOTABLE
    assert mixed_extension.promoted_group(currently_approved=False) == NOTABLE
    assert deleted_extension.promoted_group(currently_approved=False) == NOTABLE

    assert extension_with_high_adu.current_version.needs_human_review
    assert extension_with_high_adu.current_version.due_date == get_review_due_date(now)
    assert promoted_record_exists.current_version.needs_human_review
    assert promoted_record_exists.current_version.due_date == get_review_due_date(
        now + timedelta(hours=24 / target_per_day)
    )
    unlisted_latest_version = unlisted_only_extension.find_latest_version(channel=None)
    assert unlisted_latest_version.needs_human_review
    assert unlisted_latest_version.due_date == get_review_due_date(
        now + timedelta(hours=(24 / target_per_day) * 2)
    )
    assert mixed_extension_unlisted_version.reload().needs_human_review
    assert mixed_extension_unlisted_version.due_date == get_review_due_date(
        now + timedelta(hours=(24 / target_per_day) * 3)
    )
    assert mixed_extension_listed_version.reload().needs_human_review
    assert mixed_extension_listed_version.due_date == get_review_due_date(
        now + timedelta(hours=(24 / target_per_day) * 3)  # same as due due is per addon
    )
    assert deleted_extension_version.reload().needs_human_review
    assert deleted_extension_version.due_date == get_review_due_date(
        now + timedelta(hours=(24 / target_per_day) * 4)
    )
