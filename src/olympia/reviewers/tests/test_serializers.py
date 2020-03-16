# -*- coding: utf-8 -*-
import json

from datetime import datetime

from django.core.cache import cache

from rest_framework.exceptions import NotFound
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.amo.urlresolvers import reverse
from olympia.files.models import FileValidation
from olympia.lib.git import AddonGitRepository
from olympia.lib.tests.test_git import apply_changes
from olympia.reviewers.models import CannedResponse
from olympia.reviewers.serializers import (
    AddonBrowseVersionSerializer, CannedResponseSerializer,
    FileEntriesDiffSerializer, FileEntriesSerializer)
from olympia.versions.models import License
from olympia.versions.tasks import extract_version_to_git


class TestFileEntriesSerializer(TestCase):
    def setUp(self):
        super(TestFileEntriesSerializer, self).setUp()

        self.addon = addon_factory(
            file_kw={
                'filename': 'notify-link-clicks-i18n.xpi',
                'is_webextension': True})
        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()

    def get_serializer(self, obj, **extra_context):
        api_version = api_settings.DEFAULT_VERSION
        request = APIRequestFactory().get('/api/%s/' % api_version)
        request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = api_version
        extra_context.setdefault('request', request)

        return FileEntriesSerializer(
            instance=obj, context=extra_context)

    def serialize(self, obj, **extra_context):
        return self.get_serializer(obj, **extra_context).data

    def test_basic(self):
        file = self.addon.current_version.current_file

        data = self.serialize(file)

        assert data['id'] == file.pk
        assert data['status'] == 'public'
        assert data['hash'] == ''
        assert data['is_webextension'] is True
        assert data['created'] == (
            file.created.replace(microsecond=0).isoformat() + 'Z')
        assert data['url'] == (
            'http://testserver/firefox/downloads/file/{}'
            '/notify-link-clicks-i18n.xpi?src=').format(file.pk)

        assert data['selected_file'] == 'manifest.json'
        assert data['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.addon.current_version.pk,
                'filename': 'manifest.json'
            }
        ))
        assert not data['uses_unknown_minified_code']

        assert set(data['entries'].keys()) == {
            'README.md',
            '_locales', '_locales/de', '_locales/en', '_locales/nb_NO',
            '_locales/nl', '_locales/ru', '_locales/sv', '_locales/ja',
            '_locales/de/messages.json', '_locales/en/messages.json',
            '_locales/ja/messages.json', '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json', '_locales/ru/messages.json',
            '_locales/sv/messages.json', 'background-script.js',
            'content-script.js', 'icons', 'icons/LICENSE', 'icons/link-48.png',
            'manifest.json'}

        manifest_data = data['entries']['manifest.json']
        assert manifest_data['depth'] == 0
        assert manifest_data['filename'] == u'manifest.json'
        assert manifest_data['sha256'] == (
            '71d4122c0f2f78e089136602f88dbf590f2fa04bb5bc417454bf21446d6cb4f0')
        assert manifest_data['mimetype'] == 'application/json'
        assert manifest_data['mime_category'] == 'text'
        assert manifest_data['path'] == u'manifest.json'
        assert manifest_data['size'] == 622

        assert isinstance(manifest_data['modified'], datetime)

        ja_locale_data = data['entries']['_locales/ja']

        assert ja_locale_data['depth'] == 1
        assert ja_locale_data['mime_category'] == 'directory'
        assert ja_locale_data['filename'] == 'ja'
        assert ja_locale_data['sha256'] is None
        assert ja_locale_data['mimetype'] == 'application/octet-stream'
        assert ja_locale_data['path'] == u'_locales/ja'
        assert ja_locale_data['size'] is None
        assert isinstance(ja_locale_data['modified'], datetime)

        assert '"manifest_version": 2' in data['content']
        assert 'id": "notify-link-clicks-i18n@notzilla.org' in data['content']
        assert data['platform'] == 'all'
        assert data['is_mozilla_signed_extension'] is False

    def test_requested_file(self):
        file = self.addon.current_version.current_file

        data = self.serialize(file, file='icons/LICENSE')

        assert data['id'] == file.pk
        assert set(data['entries'].keys()) == {
            'README.md',
            '_locales', '_locales/de', '_locales/en', '_locales/nb_NO',
            '_locales/nl', '_locales/ru', '_locales/sv', '_locales/ja',
            '_locales/de/messages.json', '_locales/en/messages.json',
            '_locales/ja/messages.json', '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json', '_locales/ru/messages.json',
            '_locales/sv/messages.json', 'background-script.js',
            'content-script.js', 'icons', 'icons/LICENSE', 'icons/link-48.png',
            'manifest.json'}

        assert data['selected_file'] == 'icons/LICENSE'
        assert data['content'].startswith(
            'The "link-48.png" icon is taken from the Geomicons')
        assert data['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.addon.current_version.pk,
                'filename': 'icons/LICENSE'
            }
        ))

    def test_requested_file_with_non_existent_file(self):
        file = self.addon.current_version.current_file
        with self.assertRaises(NotFound):
            self.serialize(file, file='UNKNOWN_FILE')

    def test_supports_search_plugin(self):
        self.addon = addon_factory(file_kw={'filename': 'search_20190331.xml'})
        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()
        file = self.addon.current_version.current_file

        data = self.serialize(file)

        assert data['id'] == file.pk
        assert set(data['entries'].keys()) == {'search_20190331.xml'}
        assert data['selected_file'] == 'search_20190331.xml'
        assert data['content'].startswith(
            '<?xml version="1.0" encoding="utf-8"?>')
        assert data['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.addon.current_version.pk,
                'filename': 'search_20190331.xml'
            }
        ))

    def test_get_entries_cached(self):
        file = self.addon.current_version.current_file
        serializer = self.get_serializer(file)

        # start serialization
        data = serializer.data
        commit = serializer._get_commit(file)

        assert serializer._entries == data['entries']

        key = 'reviewers:fileentriesserializer:entries:{}'.format(commit.hex)
        cached_data = cache.get(key)

        # We exclude `manifest.json` here to test that in a separate step
        # because the sha256 calculation will overwrite `serializer._entries`
        # but doesn't update the cache (yet at least) to avoid cache
        # cache syncronisation issues
        expected_keys = {
            'README.md',
            '_locales', '_locales/de', '_locales/en', '_locales/nb_NO',
            '_locales/nl', '_locales/ru', '_locales/sv', '_locales/ja',
            '_locales/de/messages.json', '_locales/en/messages.json',
            '_locales/ja/messages.json', '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json', '_locales/ru/messages.json',
            '_locales/sv/messages.json', 'background-script.js',
            'content-script.js', 'icons', 'icons/LICENSE', 'icons/link-48.png'}

        for key in expected_keys:
            assert cached_data[key] == data['entries'][key]

    def test_dont_render_content_binary_file(self):
        file = self.addon.current_version.current_file
        data = self.serialize(file, file='icons/link-48.png')
        assert data['content'] == ''

    def test_sha256_only_calculated_or_fetched_for_selected_file(self):
        file = self.addon.current_version.current_file

        data = self.serialize(file, file='icons/LICENSE')

        assert data['entries']['manifest.json']['sha256'] is None
        assert data['entries']['icons/LICENSE']['sha256'] == (
            'b48e66c02fe62dd47521def7c5ea11b86af91b94c23cfdf67592e1053952ed55')

        data = self.serialize(file, file='manifest.json')
        assert data['entries']['manifest.json']['sha256'] == (
            '71d4122c0f2f78e089136602f88dbf590f2fa04bb5bc417454bf21446d6cb4f0')
        assert data['entries']['icons/LICENSE']['sha256'] is None

    def test_uses_unknown_minified_code(self):
        validation_data = {
            'metadata': {
                'unknownMinifiedFiles': ['content-script.js']
            }
        }

        fobj = self.addon.current_version.current_file

        FileValidation.objects.create(
            file=fobj, validation=json.dumps(validation_data))

        data = self.serialize(fobj, file='content-script.js')
        assert data['uses_unknown_minified_code']

        data = self.serialize(fobj, file='background-script.js')
        assert not data['uses_unknown_minified_code']


class TestFileEntriesDiffSerializer(TestCase):
    def setUp(self):
        super(TestFileEntriesDiffSerializer, self).setUp()

        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()

    def create_new_version_for_addon(self, xpi_filename):
        addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': xpi_filename})

        extract_version_to_git(addon.current_version.pk)

        addon.current_version.refresh_from_db()
        parent_version = addon.current_version

        new_version = version_factory(
            addon=addon, file_kw={
                'filename': xpi_filename,
                'is_webextension': True,
            }
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        return addon, repo, parent_version, new_version

    def get_serializer(self, obj, **extra_context):
        api_version = api_settings.DEFAULT_VERSION
        request = APIRequestFactory().get('/api/%s/' % api_version)
        request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = api_version
        extra_context.setdefault('request', request)

        return FileEntriesDiffSerializer(
            instance=obj, context=extra_context)

    def serialize(self, obj, **extra_context):
        return self.get_serializer(obj, **extra_context).data

    def test_basic(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, 'Updated test file\n', 'test.txt')
        apply_changes(repo, new_version, '', 'README.md', delete=True)

        file = self.addon.current_version.current_file

        data = self.serialize(file, parent_version=parent_version)

        assert data['id'] == file.pk
        assert data['parent_id'] == parent_version.current_file.pk
        assert data['status'] == 'public'
        assert data['hash'] == ''
        assert data['is_webextension'] is True
        assert data['created'] == (
            file.created.replace(microsecond=0).isoformat() + 'Z')
        assert data['url'] == (
            'http://testserver/firefox/downloads/file/{}'
            '/webextension_no_id.xpi?src=').format(file.pk)

        assert data['selected_file'] == 'manifest.json'
        assert data['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.addon.current_version.pk,
                'filename': 'manifest.json'
            }
        ))
        assert not data['uses_unknown_minified_code']

        assert set(data['entries'].keys()) == {
            'manifest.json', 'README.md', 'test.txt'}

        # The API always renders a diff, even for unmodified files.
        assert data['diff'] is not None

        assert not data['uses_unknown_minified_code']

        # Unmodified file
        manifest_data = data['entries']['manifest.json']
        assert manifest_data['depth'] == 0
        assert manifest_data['filename'] == u'manifest.json'
        assert manifest_data['sha256'] == (
            'bf9b0744c0011cad5caa55236951eda523f17676e91353a64a32353eac798631')
        assert manifest_data['mimetype'] == 'application/json'
        assert manifest_data['mime_category'] == 'text'
        assert manifest_data['path'] == u'manifest.json'
        assert manifest_data['size'] == 621
        assert manifest_data['status'] == ''
        assert isinstance(manifest_data['modified'], datetime)

        # Added a new file
        test_txt_data = data['entries']['test.txt']
        assert test_txt_data['depth'] == 0
        assert test_txt_data['filename'] == u'test.txt'
        assert test_txt_data['sha256'] is None
        assert test_txt_data['mimetype'] == 'text/plain'
        assert test_txt_data['mime_category'] == 'text'
        assert test_txt_data['path'] == u'test.txt'
        assert test_txt_data['size'] == 18
        assert test_txt_data['status'] == 'A'

        # Deleted file
        readme_data = data['entries']['README.md']
        assert readme_data['status'] == 'D'
        assert readme_data['depth'] == 0
        assert readme_data['filename'] == 'README.md'
        assert readme_data['sha256'] is None
        # Not testing mimetype as text/markdown is missing in travis mimetypes
        # database. But it doesn't matter much here since we're primarily
        # after the git status.
        assert readme_data['mime_category'] is None
        assert readme_data['path'] == u'README.md'
        assert readme_data['size'] is None
        assert readme_data['modified'] is None

    def test_serialize_deleted_file(self):
        parent_version = self.addon.current_version
        new_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)
        apply_changes(repo, new_version, '', 'manifest.json', delete=True)

        file = self.addon.current_version.current_file
        data = self.serialize(file, parent_version=parent_version)

        assert data['download_url'] is None
        # We deleted the selected file, so there should be a diff.
        assert data['diff'] is not None
        assert data['diff']['mode'] == 'D'

    def test_recreate_parent_dir_of_deleted_file(self):
        addon, repo, parent_version, new_version = \
            self.create_new_version_for_addon(
                'webextension_signed_already.xpi')

        apply_changes(
            repo, new_version, '', 'META-INF/mozilla.rsa', delete=True)

        data = self.serialize(
            new_version.current_file, parent_version=parent_version)

        entries_by_file = {
            e['path']: e for e in data['entries'].values()
        }
        parent_dir = 'META-INF'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['depth'] == 0
        assert parent['filename'] == parent_dir
        assert parent['sha256'] is None
        assert parent['mime_category'] == 'directory'
        assert parent['mimetype'] == 'application/octet-stream'
        assert parent['path'] == parent_dir
        assert parent['size'] is None
        assert parent['modified'] is None

    def test_recreate_nested_parent_dir_of_deleted_file(self):
        addon, repo, parent_version, new_version = \
            self.create_new_version_for_addon('https-everywhere.xpi')

        apply_changes(
            repo,
            new_version,
            '',
            '_locales/ru/messages.json',
            delete=True)

        data = self.serialize(
            new_version.current_file, parent_version=parent_version)

        entries_by_file = {
            e['path']: e for e in data['entries'].values()
        }
        parent_dir = '_locales/ru'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['depth'] == 1
        assert parent['filename'] == 'ru'
        assert parent['path'] == parent_dir

    def test_do_not_recreate_parent_dir_of_deleted_root_file(self):
        addon, repo, parent_version, new_version = \
            self.create_new_version_for_addon(
                'webextension_signed_already.xpi')

        apply_changes(
            repo, new_version, '', 'manifest.json', delete=True)

        data = self.serialize(
            new_version.current_file, parent_version=parent_version)

        entries_by_file = {
            e['path']: e for e in data['entries'].values()
        }

        # Since we just deleted a root file, no additional entries
        # should have been added for its parent directory.
        assert list(sorted(entries_by_file.keys())) == [
            'META-INF',
            'META-INF/mozilla.rsa',
            'index.js',
            'manifest.json',
        ]

    def test_do_not_recreate_parent_dir_if_it_exists(self):
        addon, repo, parent_version, new_version = \
            self.create_new_version_for_addon('https-everywhere.xpi')

        # Delete a file within a directory but modify another file.
        # This will preserve the directory, i.e. we won't have to
        # recreate it.
        apply_changes(
            repo,
            new_version,
            '',
            'chrome-resources/css/chrome_shared.css',
            delete=True)
        apply_changes(
            repo,
            new_version,
            '/* new content */',
            'chrome-resources/css/widgets.css')

        data = self.serialize(
            new_version.current_file, parent_version=parent_version)

        entries_by_file = {
            e['path']: e for e in data['entries'].values()
        }
        parent_dir = 'chrome-resources/css'
        assert parent_dir in entries_by_file.keys()

        parent = entries_by_file[parent_dir]
        assert parent['mime_category'] == 'directory'
        assert parent['mimetype'] == 'application/octet-stream'
        assert parent['path'] == parent_dir
        # Since the directory is returned from git, it will have a real
        # modified timestamp.
        assert parent['modified'] is not None

    def test_expose_grandparent_dir_deleted_subfolders(self):
        addon, repo, parent_version, new_version = \
            self.create_new_version_for_addon('deeply-nested.zip')

        apply_changes(
            repo,
            new_version,
            '',
            'chrome/icons/de/foo.png',
            delete=True)

        data = self.serialize(
            new_version.current_file, parent_version=parent_version)

        entries_by_file = {
            e['path']: e for e in data['entries'].values()
        }
        # Check that we correctly include grand-parent folders too
        # See https://github.com/mozilla/addons-server/issues/13092
        grandparent_dir = 'chrome'
        assert grandparent_dir in entries_by_file.keys()

        parent = entries_by_file[grandparent_dir]
        assert parent['mime_category'] == 'directory'
        assert parent['mimetype'] == 'application/octet-stream'
        assert parent['path'] == grandparent_dir
        assert parent['depth'] == 0

    def test_selected_file_unmodified(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )
        AddonGitRepository.extract_and_commit_from_version(new_version)

        file = self.addon.current_version.current_file

        data = self.serialize(file, parent_version=parent_version)

        assert data['id'] == file.pk

        # Unmodified file
        manifest_data = data['entries']['manifest.json']
        assert manifest_data['depth'] == 0
        assert manifest_data['filename'] == u'manifest.json'
        assert manifest_data['sha256'] == (
            'bf9b0744c0011cad5caa55236951eda523f17676e91353a64a32353eac798631')
        assert manifest_data['mimetype'] == 'application/json'
        assert manifest_data['mime_category'] == 'text'
        assert manifest_data['path'] == u'manifest.json'
        assert manifest_data['size'] == 621
        assert manifest_data['status'] == ''
        assert isinstance(manifest_data['modified'], datetime)

        assert data['diff'] is not None

    def test_uses_unknown_minified_code(self):
        parent_version = self.addon.current_version

        new_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )
        AddonGitRepository.extract_and_commit_from_version(new_version)

        file = self.addon.current_version.current_file

        validation_data = {
            'metadata': {
                'unknownMinifiedFiles': ['README.md']
            }
        }

        # Let's create a validation for the parent but not the current file
        # which will result in us notifying the frontend of a minified file
        # as well
        current_validation = FileValidation.objects.create(
            file=file, validation=json.dumps(validation_data))

        data = self.serialize(
            file, parent_version=parent_version, file='README.md')
        assert data['uses_unknown_minified_code']

        data = self.serialize(
            file, parent_version=parent_version, file='manifest.json')
        assert not data['uses_unknown_minified_code']

        current_validation.delete()

        # Creating a validation object for the current one works as well
        FileValidation.objects.create(
            file=parent_version.current_file,
            validation=json.dumps(validation_data))

        data = self.serialize(
            file, parent_version=parent_version, file='README.md')
        assert data['uses_unknown_minified_code']

        data = self.serialize(
            file, parent_version=parent_version, file='manifest.json')
        assert not data['uses_unknown_minified_code']


class TestAddonBrowseVersionSerializer(TestCase):
    def setUp(self):
        super(TestAddonBrowseVersionSerializer, self).setUp()

        license = License.objects.create(
            name={
                'en-US': u'My License',
                'fr': u'Mä Licence',
            },
            text={
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            url='http://license.example.com/'

        )

        self.addon = addon_factory(
            file_kw={
                'hash': 'fakehash',
                'is_mozilla_signed_extension': True,
                'platform': amo.PLATFORM_ALL.id,
                'size': 42,
                'filename': 'notify-link-clicks-i18n.xpi',
                'is_webextension': True
            },
            version_kw={
                'license': license,
                'min_app_version': '50.0',
                'max_app_version': '*',
                'release_notes': {
                    'en-US': u'Release notes in english',
                    'fr': u'Notes de version en français',
                },
                'reviewed': self.days_ago(0),
            }
        )

        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.reload()
        assert self.addon.current_version.release_notes
        self.version = self.addon.current_version

    def get_serializer(self, **extra_context):
        api_version = api_settings.DEFAULT_VERSION
        request = APIRequestFactory().get('/api/%s/' % api_version)
        request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = api_version
        extra_context.setdefault('request', request)

        return AddonBrowseVersionSerializer(
            instance=self.version, context=extra_context)

    def serialize(self, **extra_context):
        return self.get_serializer(**extra_context).data

    def test_basic(self):
        # Overwritten partially to remove `files` related tests since we don't
        # include it in our simplified serializer version
        data = self.serialize()
        assert data['id'] == self.version.pk

        assert data['channel'] == 'listed'
        assert data['reviewed'] == (
            self.version.reviewed.replace(microsecond=0).isoformat() + 'Z')

        # Custom fields
        validation_url_json = absolutify(reverse(
            'devhub.json_file_validation', args=[
                self.addon.slug, self.version.current_file.id]))
        validation_url = absolutify(reverse('devhub.file_validation', args=[
            self.addon.slug, self.version.current_file.id]))

        assert data['validation_url_json'] == validation_url_json
        assert data['validation_url'] == validation_url

        # That's been tested by TestFileEntriesSerializer
        assert 'file' in data

        assert data['has_been_validated'] is False

        assert dict(data['addon']) == {
            'id': self.addon.id,
            'slug': self.addon.slug,
            'name': {'en-US': self.addon.name},
            'icon_url': absolutify(self.addon.get_icon_url(64))
        }


class TestCannedResponseSerializer(TestCase):

    def test_basic(self):
        response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'test',
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        data = CannedResponseSerializer(instance=response).data

        assert data == {
            'id': response.id,
            'title': 'Terms of services',
            'response': 'test',
            'category': 'Other',
        }
