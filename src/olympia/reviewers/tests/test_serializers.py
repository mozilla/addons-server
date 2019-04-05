# -*- coding: utf-8 -*-
import os
from datetime import datetime

import pytest

from mock import MagicMock

from rest_framework.test import APIRequestFactory
from rest_framework.settings import api_settings

from django.core.cache import cache
from django.conf import settings
from django.utils.encoding import force_bytes

from olympia import amo
from olympia.reviewers.serializers import (
    AddonBrowseVersionSerializer, FileEntriesSerializer)
from olympia.amo.urlresolvers import reverse
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.versions.tasks import extract_version_to_git
from olympia.versions.models import License


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
        assert ja_locale_data['sha256'] == ''
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
        assert cache.get(key) == data['entries']


@pytest.mark.parametrize(
    'entry, filename, expected_category, expected_mimetype',
    [
        (MagicMock(type='blob'), 'blank.pdf', 'binary', 'application/pdf'),
        (MagicMock(type='blob'), 'blank.txt', 'text', 'text/plain'),
        (MagicMock(type='blob'), 'empty_bat.exe', 'binary',
                                 'application/x-dosexec'),
        (MagicMock(type='blob'), 'fff.gif', 'image', 'image/gif'),
        (MagicMock(type='blob'), 'foo.css', 'text', 'text/css'),
        (MagicMock(type='blob'), 'foo.html', 'text', 'text/html'),
        (MagicMock(type='blob'), 'foo.js', 'text', 'application/javascript'),
        (MagicMock(type='blob'), 'foo.py', 'text', 'text/x-python'),
        (MagicMock(type='blob'), 'image.jpg', 'image', 'image/jpeg'),
        (MagicMock(type='blob'), 'image.png', 'image', 'image/png'),
        (MagicMock(type='blob'), 'search.xml', 'text', 'application/xml'),
        (MagicMock(type='blob'), 'js_containing_png_data.js', 'text',
                                 'application/javascript'),
        (MagicMock(type='blob'), 'foo.json', 'text', 'application/json'),
        (MagicMock(type='tree'), 'foo', 'directory',
                                 'application/octet-stream'),
    ]
)
def test_file_entries_serializer_category_type(
        entry, filename, expected_category, expected_mimetype):
    serializer = FileEntriesSerializer()

    entry.name = filename

    root = os.path.join(
        settings.ROOT,
        'src/olympia/files/fixtures/files/file_viewer_filetypes/')

    if entry.type == 'tree':
        mime, category = serializer.get_entry_mime_type(entry, None)
    else:
        with open(os.path.join(root, filename), 'rb') as fobj:
            mime, category = serializer.get_entry_mime_type(
                entry, force_bytes(fobj.read()))

    assert mime == expected_mimetype
    assert category == expected_category


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

        assert data['compatibility'] == {
            'firefox': {'max': u'*', 'min': u'50.0'}
        }

        assert data['channel'] == 'listed'
        assert data['edit_url'] == absolutify(self.addon.get_dev_url(
            'versions.edit', args=[self.version.pk], prefix_only=True))
        assert data['release_notes'] == {
            'en-US': u'Release notes in english',
            'fr': u'Notes de version en français',
        }
        assert data['license']
        assert dict(data['license']) == {
            'id': self.version.license.pk,
            'is_custom': True,
            'name': {'en-US': u'My License', 'fr': u'Mä Licence'},
            'text': {
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            'url': 'http://license.example.com/',
        }
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
