import os
import pytest
import shutil
import tempfile
from unittest import mock

from django.conf import settings
from django.core.files import File as DjangoFile

from PIL import Image
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size
from olympia.versions.models import VersionPreview

from ..tasks import (
    recreate_theme_previews,
    resize_icon,
    update_addon_average_daily_users,
    update_addon_hotness,
    update_addon_weekly_downloads,
)


@pytest.mark.django_db
def test_recreate_theme_previews():
    addon_without_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    addon_with_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    xpi_path = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/mozilla_static_theme.zip'
    )
    with open(xpi_path, 'rb') as src:
        file_ = addon_without_previews.current_version.file
        file_.file = DjangoFile(src)
        file_.save()
    with open(xpi_path, 'rb') as src:
        file_ = addon_with_previews.current_version.file
        file_.file = DjangoFile(src)
        file_.save()

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
        uploadto = user_media_path('addon_icons')
        try:
            os.makedirs(uploadto)
        except OSError:
            pass
        for rsize, expected_size in zip(resize_size, final_size):
            # resize_icon moves the original
            shutil.copyfile(img, src.name)
            src_image = Image.open(src.name)
            assert src_image.size == original_size
            dest_name = os.path.join(uploadto, '1234')

            with mock.patch('olympia.amo.utils.pngcrush_image') as pngcrush_mock:
                return_value = resize_icon(src.name, dest_name, [rsize])
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
