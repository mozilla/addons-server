# -*- coding: utf-8 -*-
import mimetypes

import mock

from django.core.cache import cache

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

    def serialize(self, obj, **extra_context):
        return FileEntriesSerializer(
            instance=obj, context=extra_context).data

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

        assert data['entries']['manifest.json'] == {
            'id': file.pk,
            'binary': False,
            'depth': 0,
            'directory': False,
            'filename': 'manifest.json',
            'sha256': (
                '71d4122c0f2f78e089136602f88dbf590f2fa04bb5bc417454bf21446d'
                '6cb4f0'),
            'mimetype': 'application/json',
            'path': 'manifest.json',
            'size': 622,
            'version': file.version.version,
            'modified': mock.ANY}

        assert data['entries']['_locales/ja'] == {
            'id': file.pk,
            'binary': False,
            'depth': 1,
            'directory': True,
            'filename': 'ja',
            'sha256': '',
            'mimetype': 'application/octet-stream',
            'path': '_locales/ja',
            'size': None,
            'version': file.version.version,
            'modified': mock.ANY}

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

        assert data['content'].startswith(
            'The "link-48.png" icon is taken from the Geomicons')

    def test_is_binary(self):
        serializer = FileEntriesSerializer()

        files = [
            'foo.rdf', 'foo.xml', 'foo.js', 'foo.py' 'foo.html', 'foo.txt',
            'foo.dtd', 'foo.xul', 'foo.sh', 'foo.properties', 'foo.json',
            'foo.src', 'CHANGELOG']

        for fname in files:
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer.is_binary(fname, mime, '')

        for fname in ['foo.png', 'foo.gif', 'foo.exe', 'foo.swf']:
            mime, encoding = mimetypes.guess_type(fname)
            assert serializer.is_binary(fname, mime, '')

        for contents in ['#!/usr/bin/python', '#python', '\0x2']:
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer.is_binary('random_junk', mime, contents)

    def test_get_entries_cached(self):
        file = self.addon.current_version.current_file
        serializer = FileEntriesSerializer(instance=file)

        # start serialization
        data = serializer.data
        commit = serializer._get_commit(file)

        assert serializer._entries == data['entries']

        key = 'reviewers:fileentriesserializer:entries:{}'.format(commit.hex)
        assert cache.get(key) == data['entries']


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
        self.addon.current_version.refresh_from_db()
        self.version = self.addon.current_version

    def serialize(self, **extra_context):
        return AddonBrowseVersionSerializer(
            instance=self.version, context=extra_context).data

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
        assert data['url'] == absolutify(self.version.get_url_path())

        # Custom fields
        validation_url_json = reverse('devhub.json_file_validation', args=[
            self.addon.slug, self.version.current_file.id])
        validation_url = reverse('devhub.file_validation', args=[
            self.addon.slug, self.version.current_file.id])

        assert data['validation_url_json'] == validation_url_json
        assert data['validation_url'] == validation_url

        # That's been tested by TestFileEntriesSerializer
        assert 'file' in data

        assert data['has_been_validated'] is False
