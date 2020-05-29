from unittest import mock
import os
import pytest

from django.conf import settings
from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.tasks import (recreate_theme_previews,
                                  update_addon_average_daily_users)
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import addon_factory
from olympia.versions.models import VersionPreview


@pytest.mark.django_db
def test_recreate_theme_previews():
    xpi_path = os.path.join(
        settings.ROOT,
        'src/olympia/devhub/tests/addons/mozilla_static_theme.zip')

    addon_without_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    copy_stored_file(
        xpi_path,
        addon_without_previews.current_version.all_files[0].file_path)
    addon_with_previews = addon_factory(type=amo.ADDON_STATICTHEME)
    copy_stored_file(
        xpi_path,
        addon_with_previews.current_version.all_files[0].file_path)
    VersionPreview.objects.create(
        version=addon_with_previews.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]})

    assert addon_without_previews.current_previews.count() == 0
    assert addon_with_previews.current_previews.count() == 1
    recreate_theme_previews(
        [addon_without_previews.id, addon_with_previews.id])
    assert addon_without_previews.reload().current_previews.count() == 3
    assert addon_with_previews.reload().current_previews.count() == 3
    sizes = addon_without_previews.current_previews.values_list(
        'sizes', flat=True)
    assert list(sizes) == [
        {'image': list(amo.THEME_PREVIEW_SIZES['header']['full']),
         'thumbnail': list(amo.THEME_PREVIEW_SIZES['header']['thumbnail'])},
        {'image': list(amo.THEME_PREVIEW_SIZES['list']['full']),
         'thumbnail': list(amo.THEME_PREVIEW_SIZES['list']['thumbnail'])},
        {'image': list(amo.THEME_PREVIEW_SIZES['single']['full']),
         'thumbnail': list(amo.THEME_PREVIEW_SIZES['single']['thumbnail'])}]


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.parse_addon')
def test_create_missing_theme_previews(parse_addon_mock):
    parse_addon_mock.return_value = {}
    theme = addon_factory(type=amo.ADDON_STATICTHEME)
    preview = VersionPreview.objects.create(
        version=theme.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]})
    VersionPreview.objects.create(
        version=theme.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]})
    VersionPreview.objects.create(
        version=theme.current_version,
        sizes={'image': [123, 456], 'thumbnail': [34, 45]})

    # addon has 3 complete previews already so skip when only_missing=True
    with mock.patch('olympia.addons.tasks.generate_static_theme_preview') as p:
        recreate_theme_previews([theme.id], only_missing=True)
        assert p.call_count == 0
        recreate_theme_previews([theme.id], only_missing=False)
        assert p.call_count == 1

    # break one of the previews
    preview.update(sizes={})
    with mock.patch('olympia.addons.tasks.generate_static_theme_preview') as p:
        recreate_theme_previews([theme.id], only_missing=True)
        assert p.call_count == 1

    # And delete it so the addon only has 2 previews
    preview.delete()
    with mock.patch('olympia.addons.tasks.generate_static_theme_preview') as p:
        recreate_theme_previews([theme.id], only_missing=True)
        assert p.call_count == 1


@pytest.mark.django_db
@override_switch('local-statistics-processing', active=True)
def test_update_addon_average_daily_users_with_guid():
    addon = addon_factory(average_daily_users=0)
    count = 123
    data = [(addon.guid, count)]
    assert addon.average_daily_users == 0

    update_addon_average_daily_users(data, id_field='guid')
    addon.refresh_from_db()

    assert addon.average_daily_users == count

@pytest.mark.django_db
@override_switch('local-statistics-processing', active=True)
def test_update_addon_average_daily_users_with_pk():
    addon = addon_factory(average_daily_users=0)
    count = 123
    data = [(addon.id, count)]
    assert addon.average_daily_users == 0

    update_addon_average_daily_users(data, id_field='pk')
    addon.refresh_from_db()

    assert addon.average_daily_users == count
