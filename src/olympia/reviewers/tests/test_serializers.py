# -*- coding: utf-8 -*-
import os
import mimetypes

import mock

from django.conf import settings

from olympia import amo
from olympia.reviewers.serializers import AddonFileBrowseSerializer
from olympia.amo.urlresolvers import reverse
from olympia.amo.tests import BaseTestCase, addon_factory
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.versions.tasks import extract_version_to_git
from olympia.versions.models import License

from olympia.addons.tests.test_serializers import TestVersionSerializerOutput


class TestSimplifiedVersionSerializer(TestVersionSerializerOutput):
    """
    Overwritten partially to remove `files` related tests since we don't
    include it in our simplified serializer version
    """

    def test_file_webext_permissions(self):
        pass

    def test_basic(self):
        now = self.days_ago(0)
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
        addon = addon_factory(
            file_kw={
                'hash': 'fakehash',
                'is_webextension': True,
                'is_mozilla_signed_extension': True,
                'platform': amo.PLATFORM_WIN.id,
                'size': 42,
            },
            version_kw={
                'license': license,
                'min_app_version': '50.0',
                'max_app_version': '*',
                'release_notes': {
                    'en-US': u'Release notes in english',
                    'fr': u'Notes de version en français',
                },
                'reviewed': now,
            }
        )

        self.version = addon.current_version

        result = self.serialize()
        assert result['id'] == self.version.pk

        assert result['compatibility'] == {
            'firefox': {'max': u'*', 'min': u'50.0'}
        }

        assert result['channel'] == 'listed'
        assert result['edit_url'] == absolutify(addon.get_dev_url(
            'versions.edit', args=[self.version.pk], prefix_only=True))
        assert result['release_notes'] == {
            'en-US': u'Release notes in english',
            'fr': u'Notes de version en français',
        }
        assert result['license']
        assert dict(result['license']) == {
            'id': license.pk,
            'is_custom': True,
            'name': {'en-US': u'My License', 'fr': u'Mä Licence'},
            'text': {
                'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
            },
            'url': 'http://license.example.com/',
        }
        assert result['reviewed'] == (
            now.replace(microsecond=0).isoformat() + 'Z')
        assert result['url'] == absolutify(self.version.get_url_path())


class TestAddonFileBrowseSerializer(BaseTestCase):
    def setUp(self):
        super(TestAddonFileBrowseSerializer, self).setUp()

        self.addon = addon_factory(
            file_kw={
                'filename': 'notify-link-clicks-i18n.xpi',
                'is_webextension': True})
        extract_version_to_git(self.addon.current_version.pk)
        self.addon.current_version.refresh_from_db()

    def serialize(self, obj, **extra_context):
        return AddonFileBrowseSerializer(
            instance=obj, context=extra_context).data

    def test_basic(self):
        file = self.addon.current_version.current_file

        data = self.serialize(file)

        validation_url_json = reverse('devhub.json_file_validation', args=[
            self.addon.slug, file.id])

        assert data['id'] == file.pk
        assert data['status'] == 'public'
        assert data['validation_url_json'] == validation_url_json
        assert data['hash'] == ''
        assert data['is_webextension'] is True
        assert data['created'] == (
            file.created.replace(microsecond=0).isoformat() + 'Z')
        assert data['download_url'] == (
            'http://testserver/firefox/downloads/file/{}'
            '/notify-link-clicks-i18n.xpi?src=').format(file.pk)

        assert set(data['files'].keys()) == {
            'README.md',
            '_locales', '_locales/de', '_locales/en', '_locales/nb_NO',
            '_locales/nl', '_locales/ru', '_locales/sv', '_locales/ja',
            '_locales/de/messages.json', '_locales/en/messages.json',
            '_locales/ja/messages.json', '_locales/nb_NO/messages.json',
            '_locales/nl/messages.json', '_locales/ru/messages.json',
            '_locales/sv/messages.json', 'background-script.js',
            'content-script.js', 'icons', 'icons/LICENSE', 'icons/link-48.png',
            'manifest.json'}

        assert data['files']['manifest.json'] == {
            'id': file.pk,
            'binary': False,
            'depth': 0,
            'directory': False,
            'filename': 'manifest.json',
            'sha256': (
                '901a9b37d290ba17991d94268913400d6b7c3020f2459db93be965f44'
                '357a26e'),
            'mimetype': 'application/json',
            'path': 'manifest.json',
            'size': 623,
            'version': file.version.version,
            'modified': mock.ANY}

        assert data['files']['_locales/ja'] == {
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
        assert data['automated_signing'] is False
        assert data['has_been_validated'] is False
        assert data['is_mozilla_signed_extension'] is False

    def test_requested_file(self):
        file = self.addon.current_version.current_file

        data = self.serialize(file, file='icons/LICENSE')

        assert data['id'] == file.pk
        assert set(data['files'].keys()) == {
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
        serializer = AddonFileBrowseSerializer()

        files = [
            'foo.rdf', 'foo.xml', 'foo.js', 'foo.py' 'foo.html', 'foo.txt',
            'foo.dtd', 'foo.xul', 'foo.sh', 'foo.properties', 'foo.json',
            'foo.src', 'CHANGELOG']

        for fname in files:
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer._is_binary(fname, mime, '')

        for f in ['foo.png', 'foo.gif', 'foo.exe', 'foo.swf']:
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer._is_binary(fname, mime, '')

        filename = os.path.join(settings.TMP_PATH, 'test_isbinary')
        for txt in ['#!/usr/bin/python', '#python', u'\0x2']:
            open(filename, 'w').write(txt)
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer._is_binary(fname, mime, '')

        for txt in ['MZ']:
            open(filename, 'w').write(txt)
            mime, encoding = mimetypes.guess_type(fname)
            assert not serializer._is_binary(fname, mime, '')

        os.remove(filename)
