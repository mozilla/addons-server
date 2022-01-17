from unittest import mock
import os
import pytest

from django.conf import settings

from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.tasks import (
    recreate_theme_previews,
    update_addon_average_daily_users,
    update_addon_hotness,
    update_addon_weekly_downloads,
)
from olympia.amo.tests import addon_factory, root_storage
from olympia.versions.models import VersionPreview


@pytest.mark.django_db
def test_recreate_theme_previews():
    xpi_path = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/mozilla_static_theme.zip'
    )

    addon_without_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    root_storage.copy_stored_file(
        xpi_path, addon_without_previews.current_version.file.file_path
    )
    addon_with_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    root_storage.copy_stored_file(
        xpi_path, addon_with_previews.current_version.file.file_path
    )
    VersionPreview.objects.create(
        version=addon_with_previews.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]},
    )

    assert addon_without_previews.current_previews.count() == 0
    assert addon_with_previews.current_previews.count() == 1
    recreate_theme_previews([addon_without_previews.id, addon_with_previews.id])
    assert addon_without_previews.reload().current_previews.count() == 2
    assert addon_with_previews.reload().current_previews.count() == 2
    sizes = addon_without_previews.current_previews.values_list('sizes', flat=True)
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
    with mock.patch(
        f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
    ) as gen_preview, mock.patch(f'{PATCH_PATH}.resize_image') as resize:
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
    with mock.patch(
        f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
    ) as gen_preview, mock.patch(f'{PATCH_PATH}.resize_image') as resize:
        recreate_theme_previews([theme.id], only_missing=True)
        assert gen_preview.call_count == 1
        assert resize.call_count == 0

    # Preview is correct dimensions but wrong format, call generate_static_theme_preview
    amo_preview.sizes['image_format'] = 'foo'
    amo_preview.save()
    firefox_preview.save()
    extra_preview.save()
    assert VersionPreview.objects.count() == 3
    with mock.patch(
        f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
    ) as gen_preview, mock.patch(f'{PATCH_PATH}.resize_image') as resize:
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
    with mock.patch(
        f'{PATCH_PATH}.generate_static_theme_preview.apply_async'
    ) as gen_preview, mock.patch(f'{PATCH_PATH}.resize_image') as resize:
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
    averages = {
        addon1.guid: {'avg_this_week': 213467, 'avg_three_weeks_before': 123467},
        addon2.guid: {
            'avg_this_week': 1,
            'avg_three_weeks_before': 1,
        },
        addon3.guid: {'avg_this_week': 213467, 'avg_three_weeks_before': 123467},
    }

    update_addon_hotness(averages=averages.items())
    addon1.refresh_from_db()
    addon2.refresh_from_db()
    addon3.refresh_from_db()

    assert addon1.hotness > 0
    # Too low averages so we set the hotness to 0.
    assert addon2.hotness == 0
    # We shouldn't have processed this add-on.
    assert addon3.hotness == 123


def test_update_addon_weekly_downloads():
    addon = addon_factory(weekly_downloads=0)
    count = 123
    data = [(addon.addonguid.hashed_guid, count)]
    assert addon.weekly_downloads == 0

    update_addon_weekly_downloads(data)
    addon.refresh_from_db()

    assert addon.weekly_downloads == count


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


def test_update_addon_weekly_downloads_skips_non_existent_addons():
    addon = addon_factory(weekly_downloads=0)
    count = 123
    invalid_hashed_guid = 'does.not@exist'
    data = [(invalid_hashed_guid, 0), (addon.addonguid.hashed_guid, count)]
    assert addon.weekly_downloads == 0

    update_addon_weekly_downloads(data)
    addon.refresh_from_db()

    assert addon.weekly_downloads == count
