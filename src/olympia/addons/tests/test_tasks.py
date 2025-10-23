import os
import shutil
import tempfile
from datetime import datetime
from unittest import mock

from django.conf import settings

import pytest
import time_machine
from PIL import Image
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import DeletedPreviewFile, DisabledAddonContent
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size
from olympia.files.models import File
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionPreview
from olympia.zadmin.models import set_config

from ..tasks import (
    delete_all_addon_media_with_backup,
    disable_addons,
    flag_high_hotness_according_to_review_tier,
    index_addons,
    recreate_theme_previews,
    resize_icon,
    restore_all_addon_media_from_backup,
    update_addon_average_daily_users,
    update_addon_hotness,
    update_addon_weekly_downloads,
)


@pytest.mark.django_db
def test_recreate_theme_previews():
    xpi_path = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/mozilla_static_theme.zip'
    )
    addon_without_previews = addon_factory(
        type=amo.ADDON_STATICTHEME, file_kw={'filename': xpi_path}
    )
    addon_with_previews = addon_factory(
        type=amo.ADDON_STATICTHEME, file_kw={'filename': xpi_path}
    )
    VersionPreview.objects.create(
        version=addon_with_previews.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]},
    )

    assert len(addon_without_previews.current_previews) == 0
    assert len(addon_with_previews.current_previews) == 1
    recreate_theme_previews([addon_without_previews.id, addon_with_previews.id])
    del addon_without_previews.reload().current_previews
    del addon_with_previews.reload().current_previews
    assert len(addon_without_previews.current_previews) == 2
    assert len(addon_with_previews.current_previews) == 2
    sizes = addon_without_previews.current_version.previews.values_list(
        'sizes', flat=True
    )
    renderings = amo.THEME_PREVIEW_RENDERINGS
    assert list(sizes) == [
        {
            'image': list(renderings['firefox']['full']),
            'thumbnail': list(renderings['firefox']['thumbnail']),
            'image_format': renderings['firefox']['image_format'],
            'thumbnail_format': renderings['firefox']['thumbnail_format'],
        },
        {
            'image': list(renderings['amo']['full']),
            'thumbnail': list(renderings['amo']['thumbnail']),
            'image_format': renderings['amo']['image_format'],
            'thumbnail_format': renderings['amo']['thumbnail_format'],
        },
    ]


PATCH_PATH = 'olympia.addons.tasks'


@pytest.mark.django_db
@mock.patch(f'{PATCH_PATH}.parse_addon')
def test_create_missing_theme_previews(parse_addon_mock):
    parse_addon_mock.return_value = {}
    theme = addon_factory(type=amo.ADDON_STATICTHEME)
    amo_preview = VersionPreview.objects.create(
        version=theme.current_version,
        sizes={
            'image': amo.THEME_PREVIEW_RENDERINGS['amo']['full'],
            'thumbnail': amo.THEME_PREVIEW_RENDERINGS['amo']['thumbnail'],
            'thumbnail_format': amo.THEME_PREVIEW_RENDERINGS['amo']['thumbnail_format'],
            'image_format': amo.THEME_PREVIEW_RENDERINGS['amo']['image_format'],
        },
    )
    firefox_preview = VersionPreview.objects.create(
        version=theme.current_version,
        sizes={
            'image': amo.THEME_PREVIEW_RENDERINGS['firefox']['full'],
            'thumbnail': amo.THEME_PREVIEW_RENDERINGS['firefox']['thumbnail'],
        },
    )
    # add another extra preview size that should be ignored
    extra_preview = VersionPreview.objects.create(
        version=theme.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]},
    )

    # addon has all the complete previews already so skip when only_missing=True
    assert VersionPreview.objects.count() == 3
    with (
        mock.patch(
            f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
        ) as gen_preview,
        mock.patch(f'{PATCH_PATH}.resize_image') as resize,
    ):
        recreate_theme_previews([theme.id], only_missing=True)
        assert gen_preview.call_count == 0
        assert resize.call_count == 0
        recreate_theme_previews([theme.id], only_missing=False)
        assert gen_preview.call_count == 1
        assert resize.call_count == 0

    # If the add-on is missing a preview, we call generate_static_theme_preview
    VersionPreview.objects.get(id=amo_preview.id).delete()
    firefox_preview.save()
    extra_preview.save()
    assert VersionPreview.objects.count() == 2
    with (
        mock.patch(
            f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
        ) as gen_preview,
        mock.patch(f'{PATCH_PATH}.resize_image') as resize,
    ):
        recreate_theme_previews([theme.id], only_missing=True)
        assert gen_preview.call_count == 1
        assert resize.call_count == 0

    # Preview is correct dimensions but wrong format, call generate_static_theme_preview
    amo_preview.sizes['image_format'] = 'foo'
    amo_preview.save()
    firefox_preview.save()
    extra_preview.save()
    assert VersionPreview.objects.count() == 3
    with (
        mock.patch(
            f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
        ) as gen_preview,
        mock.patch(f'{PATCH_PATH}.resize_image') as resize,
    ):
        recreate_theme_previews([theme.id], only_missing=True)
        assert gen_preview.call_count == 1
        assert resize.call_count == 0

    # But we don't do the full regeneration to just get new thumbnail sizes or formats
    amo_preview.sizes['thumbnail'] = [666, 444]
    amo_preview.sizes['image_format'] = 'svg'
    amo_preview.save()
    assert amo_preview.thumbnail_dimensions == [666, 444]
    firefox_preview.sizes['thumbnail_format'] = 'gif'
    firefox_preview.save()
    assert firefox_preview.get_format('thumbnail') == 'gif'
    extra_preview.save()
    assert VersionPreview.objects.count() == 3
    with (
        mock.patch(
            f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
        ) as gen_preview,
        mock.patch(f'{PATCH_PATH}.resize_image') as resize,
    ):
        recreate_theme_previews([theme.id], only_missing=True)
        assert gen_preview.call_count == 0  # not called
        assert resize.call_count == 2
        amo_preview.reload()
        assert amo_preview.thumbnail_dimensions == [720, 92]
        firefox_preview.reload()
        assert firefox_preview.get_format('thumbnail') == 'png'

        assert VersionPreview.objects.count() == 3


@pytest.mark.django_db
def test_update_addon_average_daily_users():
    addon = addon_factory(average_daily_users=0)
    count = 123
    data = [(addon.guid, count)]
    assert addon.average_daily_users == 0

    update_addon_average_daily_users(data)
    addon.refresh_from_db()

    assert addon.average_daily_users == count


@pytest.mark.django_db
def test_update_addon_average_daily_users_case_sensitive():
    addon = addon_factory(average_daily_users=0)
    data = [(addon.guid.upper(), 123)]
    assert addon.average_daily_users == 0

    update_addon_average_daily_users(data)
    addon.refresh_from_db()

    assert addon.average_daily_users == 0


@pytest.mark.django_db
@override_switch('local-statistics-processing', active=True)
def test_update_deleted_addon_average_daily_users():
    addon = addon_factory(average_daily_users=0)
    addon.delete()
    count = 123
    data = [(addon.guid, count)]
    assert addon.average_daily_users == 0

    update_addon_average_daily_users(data)
    addon.refresh_from_db()

    assert addon.average_daily_users == count


@pytest.mark.django_db
def test_update_addon_hotness():
    addon1 = addon_factory(hotness=0, status=amo.STATUS_APPROVED)
    addon2 = addon_factory(hotness=123, status=amo.STATUS_APPROVED)
    addon3 = addon_factory(hotness=123, status=amo.STATUS_AWAITING_REVIEW)
    addon4 = addon_factory(hotness=123)
    addon4.delete()
    averages = {
        addon1.guid: {'avg_this_week': 213467, 'avg_previous_week': 123467},
        addon2.guid: {
            'avg_this_week': 1,
            'avg_previous_week': 1,
        },
        addon3.guid: {'avg_this_week': 213467, 'avg_previous_week': 123467},
        addon4.guid: {'avg_this_week': 213467, 'avg_previous_week': 123467},
    }

    update_addon_hotness(averages=averages.items())
    addon1.refresh_from_db()
    addon2.refresh_from_db()
    addon3.refresh_from_db()

    assert addon1.hotness > 0
    assert addon3.hotness > 0
    assert addon4.hotness > 0
    # Too low averages so we set the hotness to 0.
    assert addon2.hotness == 0


@time_machine.travel('2023-05-15 11:00', tick=False)
@pytest.mark.django_db
def test_flag_high_hotness_according_to_review_tier():
    user_factory(pk=settings.TASK_USER_ID)
    set_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY, '1')
    # Create some usage tiers and add add-ons in them for the task to do
    # something. The ones missing a lower, upper, or growth threshold don't
    # do anything. Also, tiers need to have a lower adu threshold above
    # MINIMUM_ADU_FOR_HOTNESS_NONTHEME (100) to do anything.
    UsageTier.objects.create(name='Not a tier with usage values')
    UsageTier.objects.create(
        name='D tier (below minimum usage for hotness)',
        lower_adu_threshold=0,
        upper_adu_threshold=100,
        growth_threshold_before_flagging=1,
    )
    UsageTier.objects.create(
        name='C tier (no growth threshold)',
        lower_adu_threshold=100,
        upper_adu_threshold=200,
    )
    UsageTier.objects.create(
        name='B tier',
        lower_adu_threshold=200,
        upper_adu_threshold=250,
        growth_threshold_before_flagging=11,
    )
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        growth_threshold_before_flagging=7,
    )
    UsageTier.objects.create(
        name='S tier (no upper threshold)',
        lower_adu_threshold=1000,
        upper_adu_threshold=None,
        growth_threshold_before_flagging=30,
    )

    not_flagged = [
        # Usage below MINIMUM_ADU_FOR_HOTNESS_NONTHEME so tier is inactive
        addon_factory(name='Low usage addon', average_daily_users=99, hotness=0.3),
        # Belongs to C tier, which doesn't have a growth threshold set.
        addon_factory(name='C tier addon', average_daily_users=100, hotness=0.3),
        # Belongs to B tier but not an extension.
        addon_factory(
            name='B tier language pack',
            type=amo.ADDON_LPAPP,
            average_daily_users=200,
            hotness=0.3,
        ),
        addon_factory(
            name='B tier theme',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=200,
            hotness=0.3,
        ),
        # Belongs to A tier but hotness below the average + threshold.
        addon_factory(
            name='A tier below threshold', average_daily_users=250, hotness=0.3
        ),
        # Belongs to S tier, which doesn't have an upper threshold. (like
        # notable, subject to human review anyway)
        addon_factory(name='S tier addon', average_daily_users=1000, hotness=0.3),
        # Belongs to A tier but already human reviewed.
        addon_factory(
            name='A tier already reviewed',
            average_daily_users=250,
            hotness=0.3,
            version_kw={'human_review_date': datetime.now()},
        ),
        # Belongs to B tier but already disabled.
        addon_factory(
            name='B tier already disabled',
            average_daily_users=200,
            hotness=0.3,
            status=amo.STATUS_DISABLED,
        ),
        # Belongs to B tier but already flagged for human review for growth
        # (see below).
        addon_factory(
            name='B tier already flagged', average_daily_users=200, hotness=0.2
        ),
    ]
    NeedsHumanReview.objects.create(
        version=not_flagged[-1].current_version, is_active=True
    )

    flagged = [
        # B tier average hotness should be 0.32, with a threshold of 11, so
        # Add-ons with a hotness over 0.43 should be flagged.
        addon_factory(name='B tier', average_daily_users=200, hotness=0.44),
        # A tier average hotness should be 0.3755, with a threshold of 7, so
        # Add-ons with a hotness over 0.4455 should be flagged.
        addon_factory(name='A tier', average_daily_users=250, hotness=0.451),
        addon_factory(
            name='A tier with inactive flags', average_daily_users=250, hotness=0.451
        ),
    ]

    # Add an inactive flag on the last one, shouldn't do anything.
    NeedsHumanReview.objects.create(
        version=flagged[-1].current_version, is_active=False
    )

    # Pretend all files were signed otherwise they would not get flagged.
    File.objects.update(is_signed=True)
    flag_high_hotness_according_to_review_tier()

    for addon in not_flagged:
        assert (
            addon.versions.latest('pk')
            .needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.HOTNESS_THRESHOLD, is_active=True
            )
            .count()
            == 0
        )

    for addon in flagged:
        version = addon.versions.latest('pk')
        assert (
            version.needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.HOTNESS_THRESHOLD, is_active=True
            ).count()
            == 1
        )

    # We've set amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY so that there would be
    # one review per day after . Since we've frozen time on a Wednesday,
    # we should get: Friday, Monday (skipping week-end), Tuesday.
    due_dates = (
        Version.objects.filter(addon__in=flagged)
        .values_list('due_date', flat=True)
        .order_by('due_date')
    )
    assert list(due_dates) == [
        datetime(2023, 5, 18, 11, 0),
        datetime(2023, 5, 19, 11, 0),
        datetime(2023, 5, 22, 11, 0),
    ]


@time_machine.travel('2023-05-15 11:00', tick=False)
@pytest.mark.django_db
def test_flag_high_hotness_according_to_review_tier_threshold_check(
    django_assert_num_queries,
):
    # Simplified version of the test above with fewer extra non-flagged add-ons
    # ensuring that we flag add-ons above the threshold, and don't flag add-ons
    # under.
    user_factory(pk=settings.TASK_USER_ID)
    UsageTier.objects.create(
        name='B tier',
        lower_adu_threshold=1000,
        upper_adu_threshold=100000,
        growth_threshold_before_flagging=0,
    )
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        growth_threshold_before_flagging=10,
    )
    # Average hotness should be 0.5666666666666667,
    # growth_threshold_before_flagging for that tier is 10 so we should flag
    # add-ons with hotness above 0.6666666666666667, meaning no add-ons should
    # be flagged.
    addon_factory(average_daily_users=251, hotness=0.55)
    addon_factory(average_daily_users=251, hotness=0.55)
    addon = addon_factory(average_daily_users=251, hotness=0.6)
    File.objects.update(is_signed=True)

    with django_assert_num_queries(4):
        # 4 queries:
        # - get all tiers
        # - get average hotness for tier A
        # - get average hotness for tier B
        # - find all add-ons to flag
        flag_high_hotness_according_to_review_tier()

    assert NeedsHumanReview.objects.count() == 0

    # Average hotness should now be 0.65, growth_threshold_before_flagging for
    # that tier is 10 so we should flag add-ons with hotness above 0.75,
    # meaning that this add-on should be flagged.
    addon.update(hotness=0.85)
    flag_high_hotness_according_to_review_tier()

    assert NeedsHumanReview.objects.count() == 1
    assert (
        addon.current_version.needshumanreview_set.filter(
            reason=NeedsHumanReview.REASONS.HOTNESS_THRESHOLD, is_active=True
        ).count()
        == 1
    )


@time_machine.travel('2023-05-15 11:00', tick=False)
@pytest.mark.django_db
def test_flag_high_hotness_according_to_review_tier_threshold_check_negative():
    user_factory(pk=settings.TASK_USER_ID)
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        growth_threshold_before_flagging=10,
    )
    # Average hotness should be negative, -0.2.
    # growth_threshold_before_flagging for that tier is 10 so we should flag
    # add-ons with hotness above -0.1, but we explicitly only flag positive
    # growth add-ons, so only the last one should be flagged.

    addon_factory(average_daily_users=251, hotness=-0.05)
    addon_factory(average_daily_users=251, hotness=-0.85)
    addon_factory(average_daily_users=251, hotness=0.0)
    addon = addon_factory(average_daily_users=251, hotness=0.1)
    File.objects.update(is_signed=True)

    flag_high_hotness_according_to_review_tier()

    assert NeedsHumanReview.objects.count() == 1
    assert (
        addon.current_version.needshumanreview_set.filter(
            reason=NeedsHumanReview.REASONS.HOTNESS_THRESHOLD, is_active=True
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_flag_high_hotness_according_to_review_tier_no_tiers_defined():
    user_factory(pk=settings.TASK_USER_ID)
    addon = addon_factory(average_daily_users=1001, file_kw={'is_signed': True})
    flag_high_hotness_according_to_review_tier()
    assert not addon.current_version.needshumanreview_set.exists()


@pytest.mark.django_db
def test_update_addon_weekly_downloads():
    addon = addon_factory(weekly_downloads=0)
    count = 123
    data = [(addon.addonguid.hashed_guid, count)]
    assert addon.weekly_downloads == 0

    update_addon_weekly_downloads(data)
    addon.refresh_from_db()

    assert addon.weekly_downloads == count


@pytest.mark.django_db
def test_update_addon_weekly_downloads_ignores_deleted_addons():
    guid = 'some@guid'
    deleted_addon = addon_factory(guid=guid)
    deleted_addon.delete()
    deleted_addon.update(guid=None)
    addon = addon_factory(guid=guid, weekly_downloads=0)
    count = 123
    data = [(addon.addonguid.hashed_guid, count)]
    assert addon.weekly_downloads == 0

    update_addon_weekly_downloads(data)
    addon.refresh_from_db()

    assert addon.weekly_downloads == count


@pytest.mark.django_db
def test_update_addon_weekly_downloads_skips_non_existent_addons():
    addon = addon_factory(weekly_downloads=0)
    count = 123
    invalid_hashed_guid = 'does.not@exist'
    data = [(invalid_hashed_guid, 0), (addon.addonguid.hashed_guid, count)]
    assert addon.weekly_downloads == 0

    update_addon_weekly_downloads(data)
    addon.refresh_from_db()

    assert addon.weekly_downloads == count


class TestResizeIcon(TestCase):
    def _uploader(self, resize_size, final_size):
        img = get_image_path('mozilla.png')
        original_size = (339, 128)

        src = tempfile.NamedTemporaryFile(
            mode='r+b', suffix='.png', delete=False, dir=settings.TMP_PATH
        )

        if not isinstance(final_size, list):
            final_size = [final_size]
            resize_size = [resize_size]
        uploadto = os.path.join(settings.MEDIA_ROOT, 'addon_icons')
        try:
            os.makedirs(uploadto)
        except OSError:
            pass
        fake_addon_id = 1234
        for rsize, expected_size in zip(resize_size, final_size, strict=True):
            # resize_icon moves the original
            shutil.copyfile(img, src.name)
            src_image = Image.open(src.name)
            assert src_image.size == original_size
            dest_name = os.path.join(
                uploadto, str(fake_addon_id // 1000), str(fake_addon_id)
            )

            with mock.patch('olympia.amo.utils.pngcrush_image') as pngcrush_mock:
                return_value = resize_icon(src.name, fake_addon_id, [rsize])
            dest_image = f'{dest_name}-{rsize}.png'
            assert pngcrush_mock.call_count == 1
            assert pngcrush_mock.call_args_list[0][0][0] == dest_image
            assert image_size(dest_image) == expected_size
            # original should have been moved to -original
            orig_image = '%s-original.png' % dest_name
            assert os.path.exists(orig_image)

            # Return value of the task should be a dict with an icon_hash key
            # containing the 8 first chars of the md5 hash of the source file,
            # which is bb362450b00f0461c6bddc6b97b3c30b.
            assert return_value == {'icon_hash': 'bb362450'}

            os.remove(dest_image)
            assert not os.path.exists(dest_image)
            os.remove(orig_image)
            assert not os.path.exists(orig_image)
        shutil.rmtree(uploadto)

        assert not os.path.exists(src.name)

    def test_resize_icon_shrink(self):
        """Image should be shrunk so that the longest side is 32px."""

        resize_size = 32
        final_size = (32, 12)

        self._uploader(resize_size, final_size)

    def test_resize_icon_enlarge(self):
        """Image stays the same, since the new size is bigger than both sides."""

        resize_size = 350
        final_size = (339, 128)

        self._uploader(resize_size, final_size)

    def test_resize_icon_same(self):
        """Image stays the same, since the new size is the same."""

        resize_size = 339
        final_size = (339, 128)

        self._uploader(resize_size, final_size)

    def test_resize_icon_list(self):
        """Resize multiple images at once."""

        resize_size = [32, 339, 350]
        final_size = [(32, 12), (339, 128), (339, 128)]

        self._uploader(resize_size, final_size)


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.index_addons.delay')
def test_disable_addons(index_addons_mock):
    UserProfile.objects.create(pk=settings.TASK_USER_ID)
    addon = addon_factory()
    disable_addons([addon.id])

    addon.reload()
    assert addon.status == amo.STATUS_DISABLED
    assert addon.current_version is None
    assert addon.versions.all()[0].file.status == amo.STATUS_DISABLED
    assert (
        addon.versions.all()[0].file.status_disabled_reason
        == File.STATUS_DISABLED_REASONS.ADDON_DISABLE
    )

    assert ActivityLog.objects.filter(
        action=amo.LOG.FORCE_DISABLE.id, addonlog__addon=addon
    ).exists()
    index_addons_mock.assert_called_with([addon.id])


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.unindex_objects')
@mock.patch('olympia.addons.tasks.index_objects')
def test_index_addons(index_objects_mock, unindex_objects_mock):
    public_addon = addon_factory()
    incomplete_addon = addon_factory(status=amo.STATUS_NULL)
    disabled_addon = addon_factory(disabled_by_user=True)

    index_addons((public_addon.id, incomplete_addon.id, disabled_addon.id))

    index_objects_mock.assert_called_once()
    call = index_objects_mock.mock_calls[0]
    assert list(call.kwargs.keys()) == ['queryset', 'indexer_class', 'index']
    assert list(call.kwargs['queryset']) == [public_addon]
    assert call.kwargs['indexer_class'] == AddonIndexer
    assert call.kwargs['index'] is None
    unindex_objects_mock.assert_called_with(
        [incomplete_addon.id, disabled_addon.id], indexer_class=AddonIndexer
    )

    # Confirm that we don't make unnessecary calls to index_objects/unindex_objects when
    # there are no addons to index/unindex
    index_objects_mock.reset_mock()
    unindex_objects_mock.reset_mock()
    index_addons((public_addon.id,))
    index_objects_mock.assert_called_once()
    unindex_objects_mock.assert_not_called()

    index_objects_mock.reset_mock()
    unindex_objects_mock.reset_mock()
    index_addons((incomplete_addon.id,))
    index_objects_mock.assert_not_called()
    unindex_objects_mock.assert_called_once()


class TestDeleteAndRestoreAllAddonMediaWithFromBackup(TestCase):
    def setUp(self):
        patcher1 = mock.patch('olympia.addons.tasks.copy_file_to_backup_storage')
        self.addCleanup(patcher1.stop)
        self.copy_file_to_backup_storage_mock = patcher1.start()
        self.copy_file_to_backup_storage_mock.side_effect = (
            lambda fpath, type_: f'mock-backup-{os.path.basename(fpath)}'
        )
        patcher2 = mock.patch(
            'olympia.addons.tasks.download_file_contents_from_backup_storage'
        )
        self.addCleanup(patcher2.stop)
        self.download_file_contents_from_backup_storage_mock = patcher2.start()
        self.download_file_contents_from_backup_storage_mock.side_effect = (
            lambda name: f'Content for {name}'.encode('utf-8')
        )
        patcher3 = mock.patch('olympia.addons.tasks.backup_storage_enabled')
        self.addCleanup(patcher3.stop)
        self.backup_storage_enabled_mock = patcher3.start()
        self.backup_storage_enabled_mock.return_value = True

        self.addon = addon_factory()

    def test_delete_all_addon_media_with_backup(self):
        self.addon.update(icon_type='image/jpeg')
        for size in amo.ADDON_ICON_SIZES + ('original',):
            self.root_storage.copy_stored_file(
                get_image_path('sunbird-small.png'), self.addon.get_icon_path(size)
            )
        for position in range(1, 3):
            preview = self.addon.previews.create(position=position)
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.original_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.image_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.thumbnail_path
            )

        delete_all_addon_media_with_backup(self.addon.pk)

        assert DisabledAddonContent.objects.filter(addon=self.addon).exists()
        dac = DisabledAddonContent.objects.get(addon=self.addon)

        for size in amo.ADDON_ICON_SIZES + ('original',):
            assert not self.root_storage.exists(self.addon.get_icon_path(size))
        assert (
            dac.icon_backup_name
            == self.copy_file_to_backup_storage_mock.side_effect(
                self.addon.get_icon_path('original'), self.addon.icon_type
            )
        )

        assert DeletedPreviewFile.objects.count() == self.addon.previews.count() == 2
        for preview in self.addon.previews.all():
            assert not self.root_storage.exists(preview.original_path)
            assert not self.root_storage.exists(preview.image_path)
            assert not self.root_storage.exists(preview.thumbnail_path)
            assert DeletedPreviewFile.objects.get(preview=preview).backup_name == (
                self.copy_file_to_backup_storage_mock.side_effect(
                    preview.original_path, 'image/png'
                )
            )

        assert self.copy_file_to_backup_storage_mock.call_count == 3
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            self.addon.get_icon_path('original'),
            'image/jpeg',
        )
        assert self.copy_file_to_backup_storage_mock.call_args_list[1][0] == (
            self.addon.previews.all()[0].original_path,
            'image/png',
        )
        assert self.copy_file_to_backup_storage_mock.call_args_list[2][0] == (
            self.addon.previews.all()[1].original_path,
            'image/png',
        )

    def test_delete_all_addon_media_with_backup_but_backup_storage_not_enabled(self):
        self.backup_storage_enabled_mock.return_value = False
        self.addon.update(icon_type='image/jpeg')
        for size in amo.ADDON_ICON_SIZES + ('original',):
            self.root_storage.copy_stored_file(
                get_image_path('sunbird-small.png'), self.addon.get_icon_path(size)
            )
        for position in range(1, 3):
            preview = self.addon.previews.create(position=position)
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.original_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.image_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.thumbnail_path
            )

        delete_all_addon_media_with_backup(self.addon.pk)
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_icon_and_preview_does_not_exist_on_filesystem(self):
        for position in range(1, 3):
            self.addon.previews.create(addon=self.addon, position=position)
        delete_all_addon_media_with_backup(self.addon.pk)

        assert DisabledAddonContent.objects.filter(addon=self.addon).exists()
        dac = DisabledAddonContent.objects.get(addon=self.addon)
        assert dac.icon_backup_name is None
        assert DeletedPreviewFile.objects.count() == 0

    def test_delete_addon_disabled_content_instance_exists(self):
        DisabledAddonContent.objects.create(addon=self.addon, icon_backup_name='lol')
        self.test_delete_all_addon_media_with_backup()

    def test_delete_icon_original_does_not_exist(self):
        self.addon.update(icon_type='image/png')
        # No original icon.
        self.root_storage.copy_stored_file(
            get_image_path('sunbird-small.png'), self.addon.get_icon_path(128)
        )
        delete_all_addon_media_with_backup(self.addon.pk)
        assert self.copy_file_to_backup_storage_mock.call_count == 1
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            self.addon.get_icon_path(128),
            'image/png',
        )

    def test_delete_icon_pick_largest_size_that_exists(self):
        self.addon.update(icon_type='image/png')
        # No original icon, no 128 either.
        self.root_storage.copy_stored_file(
            get_image_path('sunbird-small.png'), self.addon.get_icon_path(64)
        )
        delete_all_addon_media_with_backup(self.addon.pk)
        assert self.copy_file_to_backup_storage_mock.call_count == 1
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            self.addon.get_icon_path(64),
            'image/png',
        )

    def test_delete_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        for position in range(1, 3):
            preview = self.addon.current_version.previews.create(position=position)
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.original_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.image_path
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.thumbnail_path
            )

        delete_all_addon_media_with_backup(self.addon.pk)

        # Pointless here, but useful indicator that we went through the task.
        assert DisabledAddonContent.objects.filter(addon=self.addon).exists()

        # Themes previews are automatically generated, so they shouldn't have
        # been backuped, but should no longer exist on disk.
        assert DeletedPreviewFile.objects.count() == 0
        assert self.addon.current_version.previews.count() == 2
        for preview in self.addon.current_version.previews.all():
            assert not self.root_storage.exists(preview.original_path)
            assert not self.root_storage.exists(preview.image_path)
            assert not self.root_storage.exists(preview.thumbnail_path)

        assert self.copy_file_to_backup_storage_mock.call_count == 0

    @mock.patch('olympia.addons.tasks.resize_preview')
    @mock.patch('olympia.addons.tasks.resize_icon')
    def test_restore_all_addon_media_from_backup(
        self, resize_icon_mock, resize_preview_mock
    ):
        dac = DisabledAddonContent.objects.create(
            addon=self.addon, icon_backup_name='icon-backup.jpg'
        )
        for position in range(1, 3):
            preview = self.addon.previews.create(position=position)
            dac.deletedpreviewfile_set.create(
                preview=preview,
                backup_name=f'preview-backup-{position}.png',
            )
        self.addon.update(icon_type='image/jpeg')

        restore_all_addon_media_from_backup(self.addon.pk)

        assert self.download_file_contents_from_backup_storage_mock.call_count == 3
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[0][
            0
        ] == ('icon-backup.jpg',)
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[1][
            0
        ] == ('preview-backup-1.png',)
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[2][
            0
        ] == ('preview-backup-2.png',)

        assert resize_icon_mock.delay.call_count == 1
        assert resize_icon_mock.delay.call_args_list[0][0] == (
            self.addon.get_icon_path('original'),
            self.addon.pk,
            amo.ADDON_ICON_SIZES,
        )
        assert resize_icon_mock.delay.call_args_list[0][1] == {
            'set_modified_on': self.addon.serializable_reference()
        }
        assert resize_preview_mock.delay.call_count == 2
        assert resize_preview_mock.delay.call_args_list[0][0] == (
            self.addon.previews.all()[0].original_path,
            self.addon.previews.all()[0].pk,
        )
        assert resize_preview_mock.delay.call_args_list[0][1] == {
            'set_modified_on': self.addon.serializable_reference()
        }
        assert resize_preview_mock.delay.call_args_list[1][0] == (
            self.addon.previews.all()[1].original_path,
            self.addon.previews.all()[1].pk,
        )
        assert resize_preview_mock.delay.call_args_list[1][1] == {
            'set_modified_on': self.addon.serializable_reference()
        }

        assert not DisabledAddonContent.objects.filter(pk=dac.pk).exists()

    @mock.patch('olympia.addons.tasks.resize_preview')
    @mock.patch('olympia.addons.tasks.resize_icon')
    def test_restore_all_addon_media_from_backup_but_backup_storage_not_enabled(
        self, resize_icon_mock, resize_preview_mock
    ):
        self.backup_storage_enabled_mock.return_value = False
        dac = DisabledAddonContent.objects.create(
            addon=self.addon, icon_backup_name='icon-backup.jpg'
        )
        for position in range(1, 3):
            preview = self.addon.previews.create(position=position)
            dac.deletedpreviewfile_set.create(
                preview=preview,
                backup_name=f'preview-backup-{position}.png',
            )
        self.addon.update(icon_type='image/jpeg')

        restore_all_addon_media_from_backup(self.addon.pk)

        assert self.download_file_contents_from_backup_storage_mock.call_count == 0
        assert resize_icon_mock.delay.call_count == 0
        assert resize_preview_mock.delay.call_count == 0

        # We deleted the DisabledAddonContent instance anyway.
        assert not DisabledAddonContent.objects.exists()

    @mock.patch('olympia.addons.tasks.resize_preview')
    @mock.patch('olympia.addons.tasks.resize_icon')
    def test_restore_all_addon_media_from_backup_no_disabled_addon_content_instance(
        self, resize_icon_mock, resize_preview_mock
    ):
        for position in range(1, 3):
            self.addon.previews.create(position=position)
        self.addon.update(icon_type='image/jpeg')

        restore_all_addon_media_from_backup(self.addon.pk)

        assert self.download_file_contents_from_backup_storage_mock.call_count == 0
        assert resize_icon_mock.delay.call_count == 0
        assert resize_preview_mock.delay.call_count == 0

        assert not DisabledAddonContent.objects.exists()

    @mock.patch('olympia.addons.tasks.resize_preview')
    @mock.patch('olympia.addons.tasks.resize_icon')
    def test_restore_icon_and_preview_does_not_exist_in_backup(
        self, resize_icon_mock, resize_preview_mock
    ):
        self.download_file_contents_from_backup_storage_mock.side_effect = (
            lambda path: None
        )
        dac = DisabledAddonContent.objects.create(
            addon=self.addon, icon_backup_name='does-not-exist.jpg'
        )
        for position in range(1, 3):
            preview = self.addon.previews.create(position=position)
            dac.deletedpreviewfile_set.create(
                preview=preview,
                backup_name=f'does-not-exist-either-{position}.png',
            )
        self.addon.update(icon_type='image/jpeg')

        restore_all_addon_media_from_backup(self.addon.pk)

        assert self.download_file_contents_from_backup_storage_mock.call_count == 3
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[0][
            0
        ] == ('does-not-exist.jpg',)
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[1][
            0
        ] == ('does-not-exist-either-1.png',)
        assert self.download_file_contents_from_backup_storage_mock.call_args_list[2][
            0
        ] == ('does-not-exist-either-2.png',)

        assert resize_icon_mock.delay.call_count == 0
        assert resize_preview_mock.delay.call_count == 0

        assert not DisabledAddonContent.objects.filter(pk=dac.pk).exists()

    @mock.patch('olympia.addons.tasks.recreate_theme_previews')
    def test_restore_theme(self, recreate_theme_previews_mock):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        for position in range(1, 3):
            self.addon.current_version.previews.create(position=position)

        restore_all_addon_media_from_backup(self.addon.pk)

        # Nothing to download for themes.
        assert self.download_file_contents_from_backup_storage_mock.call_count == 0

        assert not DisabledAddonContent.objects.exists()

        assert recreate_theme_previews_mock.delay.call_count == 1
        assert recreate_theme_previews_mock.delay.call_args_list[0][0] == (
            [self.addon.pk],
        )
