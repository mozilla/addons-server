from datetime import datetime

from django.conf import settings

import pytest
import time_machine

from olympia import amo
from olympia.addons.serializers import PromotedGroup
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import PromotedAddon
from olympia.reviewers.models import UsageTier
from olympia.versions.utils import get_staggered_review_due_date_generator
from olympia.zadmin.models import set_config

from ..tasks import NOTABLE_TIER_SLUG, add_high_adu_extensions_to_notable


@pytest.mark.django_db
def test_add_high_adu_extensions_to_notable_tier_absent_or_no_threshold():
    user_factory(pk=settings.TASK_USER_ID)
    set_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY, 999)

    extension_with_high_adu = addon_factory(
        average_daily_users=42, file_kw={'is_signed': True}
    )

    add_high_adu_extensions_to_notable()

    assert (
        not extension_with_high_adu.reload()
        .promoted_groups(currently_approved=False)
        .group_id
    )

    UsageTier.objects.create(slug=NOTABLE_TIER_SLUG, lower_adu_threshold=None)

    add_high_adu_extensions_to_notable()

    assert (
        not extension_with_high_adu.reload()
        .promoted_groups(currently_approved=False)
        .group_id
    )


@pytest.mark.django_db
def test_add_high_adu_extensions_to_notable():
    user_factory(pk=settings.TASK_USER_ID)
    # Arbitrary_lower_adu_threshold
    lower_adu_threshold = 1234
    UsageTier.objects.create(
        slug=NOTABLE_TIER_SLUG, lower_adu_threshold=lower_adu_threshold
    )
    # arbitrary target per day
    target_per_day = 12
    set_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY, target_per_day)

    extension_with_low_adu = addon_factory(
        average_daily_users=lower_adu_threshold - 1, file_kw={'is_signed': True}
    )
    extension_with_high_adu = addon_factory(
        average_daily_users=lower_adu_threshold, file_kw={'is_signed': True}
    )
    ignored_theme = addon_factory(
        average_daily_users=lower_adu_threshold + 1, type=amo.ADDON_STATICTHEME
    )
    already_promoted = addon_factory(
        average_daily_users=lower_adu_threshold + 1, file_kw={'is_signed': True}
    )
    PromotedAddon.objects.create(
        addon=already_promoted,
        promoted_group=PromotedGroup.objects.create(
            group_id=PROMOTED_GROUP_CHOICES.LINE
        ),
        application_id=amo.FIREFOX.id,
    )
    promoted_record_exists = addon_factory(
        average_daily_users=lower_adu_threshold + 1, file_kw={'is_signed': True}
    )
    unlisted_only_extension = addon_factory(
        average_daily_users=lower_adu_threshold + 1,
        version_kw={'channel': amo.CHANNEL_UNLISTED},
        file_kw={'is_signed': True},
    )
    mixed_extension = addon_factory(
        average_daily_users=lower_adu_threshold + 1, file_kw={'is_signed': True}
    )
    mixed_extension_listed_version = mixed_extension.current_version
    mixed_extension_listed_version.delete()
    mixed_extension_unlisted_version = version_factory(
        addon=mixed_extension, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
    )
    deleted_extension = addon_factory(
        average_daily_users=lower_adu_threshold + 1, file_kw={'is_signed': True}
    )
    deleted_extension_version = deleted_extension.current_version
    deleted_extension.delete()

    with time_machine.travel(datetime.now(), tick=False):
        now = datetime.now()
        add_high_adu_extensions_to_notable()

    assert (
        not extension_with_low_adu.reload()
        .promoted_groups(currently_approved=False)
        .group_id
    )
    assert (
        PROMOTED_GROUP_CHOICES.NOTABLE
        in extension_with_high_adu.reload()
        .promoted_groups(currently_approved=False)
        .group_id
    )
    assert not ignored_theme.reload().promoted_groups(currently_approved=False).group_id
    assert (
        PROMOTED_GROUP_CHOICES.LINE
        in already_promoted.promoted_groups(currently_approved=False).group_id
    )
    promoted_record_exists.reload()
    assert (
        PROMOTED_GROUP_CHOICES.NOTABLE
        in promoted_record_exists.promoted_groups(currently_approved=False).group_id
    )
    assert (
        PROMOTED_GROUP_CHOICES.NOTABLE
        in unlisted_only_extension.promoted_groups(currently_approved=False).group_id
    )
    assert (
        PROMOTED_GROUP_CHOICES.NOTABLE
        in mixed_extension.promoted_groups(currently_approved=False).group_id
    )
    assert (
        PROMOTED_GROUP_CHOICES.NOTABLE
        in deleted_extension.promoted_groups(currently_approved=False).group_id
    )

    generator = get_staggered_review_due_date_generator(starting=now)

    assert extension_with_high_adu.current_version.needshumanreview_set.filter(
        is_active=True
    ).exists()
    assert extension_with_high_adu.current_version.due_date == next(generator)
    assert promoted_record_exists.current_version.needshumanreview_set.filter(
        is_active=True
    ).exists()
    assert promoted_record_exists.current_version.due_date == next(generator)
    unlisted_latest_version = unlisted_only_extension.find_latest_version(channel=None)
    assert unlisted_latest_version.needshumanreview_set.filter(is_active=True).exists()
    assert unlisted_latest_version.due_date == next(generator)
    assert mixed_extension_unlisted_version.needshumanreview_set.filter(
        is_active=True
    ).exists()
    assert mixed_extension_unlisted_version.reload().due_date == next(generator)
    assert mixed_extension_listed_version.needshumanreview_set.filter(
        is_active=True
    ).exists()
    # same as due due is per addon
    assert (
        mixed_extension_listed_version.reload().due_date
        == mixed_extension_unlisted_version.due_date
    )
    assert deleted_extension_version.needshumanreview_set.filter(
        is_active=True
    ).exists()
    assert deleted_extension_version.reload().due_date == next(generator)
