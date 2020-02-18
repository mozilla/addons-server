from unittest import mock
import os
import pytest

from django.conf import settings

from olympia import amo
from olympia.addons.tasks import (
    migrate_webextensions_to_git_storage, recreate_theme_previews)
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import (
    addon_factory, TestCase, version_factory)
from olympia.files.utils import id_to_path
from olympia.versions.models import VersionPreview, source_upload_path
from olympia.lib.git import AddonGitRepository


class TestMigrateWebextensionsToGitStorage(TestCase):
    def test_basic(self):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

        migrate_webextensions_to_git_storage([addon.pk])

        repo = AddonGitRepository(addon.pk)

        assert repo.git_repository_path == os.path.join(
            settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'addon')
        assert os.listdir(repo.git_repository_path) == ['.git']

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_no_files(self, extract_mock):
        addon = addon_factory()
        addon.current_version.files.all().delete()

        migrate_webextensions_to_git_storage([addon.pk])

        extract_mock.assert_not_called()

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_skip_already_migrated_versions(self, extract_mock):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
        version_to_migrate = addon.current_version
        already_migrated_version = version_factory(
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})
        already_migrated_version.update(git_hash='already migrated...')

        migrate_webextensions_to_git_storage([addon.pk])

        # Only once instead of twice
        extract_mock.assert_called_once_with(version_to_migrate.pk)

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_migrate_versions_from_old_to_new(self, extract_mock):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
        oldest_version = addon.current_version
        oldest_version.update(created=self.days_ago(6))
        older_version = version_factory(
            created=self.days_ago(5),
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})
        most_recent = version_factory(
            created=self.days_ago(2),
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})

        migrate_webextensions_to_git_storage([addon.pk])

        # Only once instead of twice
        assert extract_mock.call_count == 3
        assert extract_mock.call_args_list[0][0][0] == oldest_version.pk
        assert extract_mock.call_args_list[1][0][0] == older_version.pk
        assert extract_mock.call_args_list[2][0][0] == most_recent.pk

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    @mock.patch('olympia.versions.tasks.extract_version_source_to_git')
    def test_migrate_versions_extracts_source(
            self, extract_source_mock, extract_mock):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
        version_to_migrate = addon.current_version
        version_to_migrate.update(
            source=source_upload_path(version_to_migrate, 'foo.tar.gz'))

        version_without_source = version_factory(
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})

        migrate_webextensions_to_git_storage([addon.pk])

        extract_source_mock.assert_called_once_with(version_to_migrate.pk)
        extract_mock.assert_has_calls([
            mock.call(version_to_migrate.pk),
            mock.call(version_without_source.pk)
        ])


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
