# -*- coding: utf-8 -*-
import hashlib
import os
import shutil
import tempfile

from django import forms
from django.conf import settings

import test_utils
from nose.tools import eq_

import amo.utils
from addons.models import Addon
from applications.models import Application, AppVersion
from files.models import File, FileUpload
from files.utils import parse_xpi
from versions.models import Version


class TestFile(test_utils.TestCase):
    """
    Tests the methods of the File model.
    """

    fixtures = ('base/addon_3615', 'base/addon_5579')

    def test_get_absolute_url(self):
        f = File.objects.get(id=67442)
        url = f.get_absolute_url(amo.FIREFOX, src='src')
        expected = ('/firefox/downloads/file/67442/'
                    'delicious_bookmarks-2.1.072-fx.xpi?src=src')
        assert url.endswith(expected), url

    def test_delete(self):
        """ Test that when the File object is deleted, it is removed from the
        filesystem """
        file = File.objects.get(pk=67442)
        filename = file.file_path
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename))
        assert not os.path.exists(filename), 'File exists at: %s' % filename
        try:
            open(filename, 'w')
            assert os.path.exists(filename)
            file.delete()
            assert not os.path.exists(filename)
        finally:
            if os.path.exists(filename):
                os.remove(filename)

        # test that the file object can be deleted without the file
        # being present
        file = File.objects.get(pk=74797)
        filename = file.file_path
        assert not os.path.exists(filename), 'File exists at: %s' % filename
        file.delete()

    def test_latest_url(self):
        # With platform.
        f = File.objects.get(id=74797)
        base = '/firefox/downloads/latest/'
        expected = base + '{0}/platform:3/addon-{0}-latest.xpi'
        eq_(expected.format(f.version.addon_id), f.latest_xpi_url())

        # No platform.
        f = File.objects.get(id=67442)
        expected = base + '{0}/addon-{0}-latest.xpi'
        eq_(expected.format(f.version.addon_id), f.latest_xpi_url())

    def test_eula_url(self):
        f = File.objects.get(id=67442)
        eq_(f.eula_url(), '/en-US/firefox/addon/3615/eula/67442')

    def test_generate_filename(self):
        f = File.objects.get(id=67442)
        eq_(f.generate_filename(), 'delicious_bookmarks-2.1.072-fx.xpi')

    def test_generate_filename_platform_specific(self):
        f = File.objects.get(id=67442)
        f.platform_id = amo.PLATFORM_MAC.id
        eq_(f.generate_filename(), 'delicious_bookmarks-2.1.072-fx-mac.xpi')

    def test_generate_filename_many_apps(self):
        f = File.objects.get(id=67442)
        f.version.compatible_apps = (amo.FIREFOX, amo.THUNDERBIRD)
        eq_(f.generate_filename(), 'delicious_bookmarks-2.1.072-fx+tb.xpi')

    def test_generate_filename_ja(self):
        f = File()
        f.version = Version(version='0.1.7')
        f.version.compatible_apps = (amo.FIREFOX,)
        f.version.addon = Addon(name=u' フォクすけといっしょ')
        eq_(f.generate_filename(),
            u'\u30d5\u30a9\u30af\u3059\u3051\u3068\u3044\u3063\u3057\u3087'
            '-0.1.7-fx.xpi')


class TestParseXpi(test_utils.TestCase):
    fixtures = ['base/apps']

    def setUp(self):
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application_id=1, version=version)

    def parse(self, addon=None):
        path = 'apps/files/fixtures/files/extension.xpi'
        xpi = os.path.join(settings.ROOT, path)
        return parse_xpi(xpi, addon)

    def test_parse_basics(self):
        # Everything but the apps
        exp = {'guid': 'guid@xpi',
               'name': 'xpi name',
               'description': 'xpi description',
               'version': '0.1',
               'homepage': 'http://homepage.com',
               'type': 1}
        parsed = self.parse()
        for key, value in exp.items():
            eq_(parsed[key], value)

    def test_parse_apps(self):
        exp = (amo.FIREFOX,
               amo.FIREFOX.id,
               AppVersion.objects.get(version='3.0'),
               AppVersion.objects.get(version='3.6.*'))
        eq_(self.parse()['apps'], [exp])

    def test_parse_apps_bad_appver(self):
        AppVersion.objects.all().delete()
        eq_(self.parse()['apps'], [])

    def test_parse_apps_bad_guid(self):
        Application.objects.all().delete()
        eq_(self.parse()['apps'], [])

    def test_guid_match(self):
        addon = Addon.objects.create(guid='guid@xpi', type=1)
        eq_(self.parse(addon)['guid'], 'guid@xpi')

    def test_guid_nomatch(self):
        addon = Addon.objects.create(guid='xxx', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        eq_(e.exception.messages, ["GUID doesn't match add-on"])

    def test_guid_dupe(self):
        Addon.objects.create(guid='guid@xpi', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse()
        eq_(e.exception.messages, ['Duplicate GUID found.'])

    def test_match_type(self):
        addon = Addon.objects.create(guid='guid@xpi', type=4)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        eq_(e.exception.messages,
            ['<em:type> does not match existing add-on'])

    # parse_dictionary
    # parse_theme
    # parse_langpack
    # parse_search_engine?


class TestFileUpload(test_utils.TestCase):

    def setUp(self):
        self._addons_path = settings.ADDONS_PATH
        settings.ADDONS_PATH = tempfile.mkdtemp()
        self.data = 'file contents'

    def tearDown(self):
        shutil.rmtree(settings.ADDONS_PATH)
        settings.ADDONS_PATH = self._addons_path

    def upload(self):
        # The data should be in chunks.
        data = list(amo.utils.chunked(self.data, 3))
        return FileUpload.from_post(data, 'filename.xpi',
                                    len(self.data))

    def test_from_post_write_file(self):
        eq_(open(self.upload().path).read(), self.data)

    def test_from_post_filename(self):
        eq_(self.upload().name, 'filename.xpi')

    def test_from_post_hash(self):
        hash = hashlib.sha256(self.data).hexdigest()
        eq_(self.upload().hash, 'sha256:%s' % hash)
