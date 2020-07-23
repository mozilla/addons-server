# -*- coding: utf-8 -*-
import hashlib
import json
import os
import tempfile
import zipfile
import shutil

from datetime import datetime

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.forms import ValidationError
from django.test.utils import override_settings
from django.utils.encoding import force_text

from unittest import mock
import pytest

from unittest.mock import patch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import chunked
from olympia.applications.models import AppVersion
from olympia.files.models import (
    File, FileUpload, FileValidation, WebextPermission,
    nfd_str, track_file_status_change)
from olympia.files.utils import (
    Extractor, check_xpi_info, parse_addon, parse_xpi)
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


class UploadTest(TestCase, amo.tests.AMOPaths):
    """
    Base for tests that mess with file uploads, safely using temp directories.
    """

    def file_path(self, *args, **kw):
        return self.file_fixture_path(*args, **kw)

    def get_upload(self, filename=None, abspath=None, validation=None,
                   addon=None, user=None, version=None, with_validation=True):
        with open(abspath if abspath else self.file_path(filename), 'rb') as f:
            xpi = f.read()
        upload = FileUpload.from_post([xpi], filename=abspath or filename,
                                      size=1234)
        upload.addon = addon
        upload.user = user
        upload.version = version
        if with_validation:
            # Simulate what fetch_manifest() does after uploading an app.
            upload.validation = validation or json.dumps({
                'errors': 0, 'warnings': 1, 'notices': 2, 'metadata': {},
                'messages': []
            })
        upload.save()
        return upload


class TestFile(TestCase, amo.tests.AMOPaths):
    """
    Tests the methods of the File model.
    """
    fixtures = ['base/addon_3615', 'base/addon_5579']

    def test_get_absolute_url(self):
        file_ = File.objects.get(id=67442)
        url = file_.get_absolute_url(src='foo')
        expected = ('/firefox/downloads/file/67442/'
                    'delicious_bookmarks-2.1.072-fx.xpi?src=foo')
        assert url.endswith(expected), url

    def test_get_url_path(self):
        file_ = File.objects.get(id=67442)
        assert absolutify(file_.get_url_path('foo')) == (
            file_.get_absolute_url(src='foo'))

    def test_get_url_path_attachment(self):
        file_ = File.objects.get(id=67442)
        expected = ('/firefox/downloads/file/67442'
                    '/type:attachment/delicious_bookmarks-2.1.072-fx.xpi'
                    '?src=foo')
        assert file_.get_url_path('foo', attachment=True) == expected

    def test_absolute_url_attachment(self):
        file_ = File.objects.get(id=67442)
        expected = ('http://testserver/firefox/downloads/file/67442'
                    '/type:attachment/delicious_bookmarks-2.1.072-fx.xpi'
                    '?src=foo')
        assert file_.get_absolute_url('foo', attachment=True) == expected

    def check_delete(self, file_, filename):
        """Test that when the File object is deleted, it is removed from the
        filesystem."""
        try:
            with storage.open(filename, 'w') as f:
                f.write('sample data\n')
            assert storage.exists(filename)
            file_.delete()
            assert not storage.exists(filename)
        finally:
            if storage.exists(filename):
                storage.delete(filename)

    def test_delete_by_version(self):
        """Test that version (soft)delete doesn't delete the file."""
        f = File.objects.get(pk=67442)
        try:
            with storage.open(f.file_path, 'w') as fi:
                fi.write('sample data\n')
            assert storage.exists(f.file_path)
            f.version.delete()
            assert storage.exists(f.file_path)
        finally:
            if storage.exists(f.file_path):
                storage.delete(f.file_path)

    def test_delete_file_path(self):
        f = File.objects.get(pk=67442)
        self.check_delete(f, f.file_path)

    def test_delete_no_file(self):
        # test that the file object can be deleted without the file
        # being present
        file = File.objects.get(pk=74797)
        filename = file.file_path
        assert not os.path.exists(filename), 'File exists at: %s' % filename
        file.delete()

    def test_delete_signal(self):
        """Test that if there's no filename, the signal is ok."""
        file = File.objects.get(pk=67442)
        file.update(filename='')
        file.delete()

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_disable_signal(self, hide_mock):
        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_APPROVED
        f.save()
        assert not hide_mock.called

        f.status = amo.STATUS_DISABLED
        f.save()
        assert hide_mock.called

    @mock.patch('olympia.files.models.File.unhide_disabled_file')
    def test_unhide_on_enable(self, unhide_mock):
        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_APPROVED
        f.save()
        assert not unhide_mock.called

        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_DISABLED
        f.save()
        assert not unhide_mock.called

        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_APPROVED
        f.save()
        assert unhide_mock.called

    def test_unhide_disabled_files(self):
        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_APPROVED
        f.filename = u'test_unhide_disabled_filés.xpi'
        with storage.open(f.guarded_file_path, 'wb') as fp:
            fp.write(b'some data\n')
        f.unhide_disabled_file()
        assert storage.exists(f.file_path)
        assert storage.open(f.file_path).size

    def test_latest_url(self):
        # With platform.
        file_ = File.objects.get(id=74797)
        actual = file_.latest_xpi_url()
        assert actual == (
            '/firefox/downloads/latest/cooliris/platform:3/'
            'addon-5579-latest.xpi')

        actual = file_.latest_xpi_url(attachment=True)
        assert actual == (
            '/firefox/downloads/latest/cooliris/type:attachment/platform:3/'
            'addon-5579-latest.xpi')

        # Same tests repeated, but now without a platform because that File is
        # available for all platforms and not just a specific one.
        file_ = File.objects.get(id=67442)
        actual = file_.latest_xpi_url()
        assert actual == (
            '/firefox/downloads/latest/a3615/addon-3615-latest.xpi')

        actual = file_.latest_xpi_url(attachment=True)
        assert actual == (
            '/firefox/downloads/latest/a3615/type:attachment/'
            'addon-3615-latest.xpi')

    def test_generate_filename(self):
        f = File.objects.get(id=67442)
        assert f.generate_filename() == 'delicious_bookmarks-2.1.072-fx.xpi'

    def test_pretty_filename(self):
        f = File.objects.get(id=67442)
        f.generate_filename()
        assert f.pretty_filename() == 'delicious_bookmarks-2.1.072-fx.xpi'

    def test_pretty_filename_short(self):
        f = File.objects.get(id=67442)
        f.version.addon.name = 'A Place Where The Sea Remembers Your Name'
        f.generate_filename()
        assert f.pretty_filename() == 'a_place_where_the...-2.1.072-fx.xpi'

    def test_generate_filename_platform_specific(self):
        f = File.objects.get(id=67442)
        f.platform = amo.PLATFORM_MAC.id
        assert f.generate_filename() == (
            'delicious_bookmarks-2.1.072-fx-mac.xpi')

    def test_generate_filename_many_apps(self):
        f = File.objects.get(id=67442)
        f.version._compatible_apps = {amo.FIREFOX: None, amo.ANDROID: None}
        # After adding sorting for compatible_apps, above becomes
        # (amo.ANDROID, amo.FIREFOX) so 'an+fx' is appended to filename
        # instead of 'fx+an'
        # See: https://github.com/mozilla/addons-server/issues/3358
        assert f.generate_filename() == 'delicious_bookmarks-2.1.072-an+fx.xpi'

    def test_generate_filename_ja(self):
        f = File()
        f.version = Version(version='0.1.7')
        f.version._compatible_apps = {amo.FIREFOX: None}
        f.version.addon = Addon(name=u' フォクすけ  といっしょ')
        assert f.generate_filename() == 'addon-0.1.7-fx.xpi'

    def test_generate_hash(self):
        file_ = File()
        file_.version = Version.objects.get(pk=81551)
        filename = self.xpi_path('delicious_bookmarks-2.1.106-fx')
        assert file_.generate_hash(
            filename).startswith('sha256:fd277d45ab44f6240e')

        file_ = File.objects.get(pk=67442)
        with storage.open(file_.file_path, 'wb') as fp:
            fp.write(b'some data\n')
        with storage.open(file_.guarded_file_path, 'wb') as fp:
            fp.write(b'some data guarded\n')
        assert file_.generate_hash().startswith('sha256:5aa03f96c77536579166f')
        file_.status = amo.STATUS_DISABLED
        assert file_.generate_hash().startswith('sha256:6524f7791a35ef4dd4c6f')
        file_.status = amo.STATUS_APPROVED
        assert file_.generate_hash().startswith('sha256:5aa03f96c77536579166f')

    def test_addon(self):
        f = File.objects.get(pk=67442)
        addon_id = f.version.addon_id
        addon = Addon.objects.get(pk=addon_id)
        addon.update(status=amo.STATUS_DELETED)
        assert f.addon.id == addon_id

    def _cmp_permission(self, perm_a, perm_b):
        return (perm_a.name == perm_b.name and
                perm_a.description == perm_b.description)

    def test_webext_permissions_list_string_only(self):
        file_ = File.objects.get(pk=67442)
        file_.update(is_webextension=True)
        permissions = [u'iamstring',
                       u'iamnutherstring',
                       {u'iamadict': u'hmm'},
                       [u'iamalistinalist', u'indeedy'],
                       13,
                       u'laststring!',
                       u'iamstring',
                       u'iamnutherstring',
                       u'laststring!']
        WebextPermission.objects.create(permissions=permissions, file=file_)

        # Strings only please.No duplicates.
        assert file_.webext_permissions_list == [
            u'iamstring', u'iamnutherstring', u'laststring!']

    def test_optional_permissions_list_string_only(self):
        file_ = File.objects.get(pk=67442)
        file_.update(is_webextension=True)
        optional_permissions = [u'iamstring',
                                u'iamnutherstring',
                                {u'iamadict': u'hmm'},
                                [u'iamalistinalist', u'indeedy'],
                                13,
                                u'laststring!',
                                u'iamstring',
                                u'iamnutherstring',
                                u'laststring!']
        WebextPermission.objects.create(
            optional_permissions=optional_permissions, file=file_)

        # Strings only please.No duplicates.
        assert file_.optional_permissions_list == [
            u'iamstring', u'iamnutherstring', u'laststring!']

    def test_current_file_path(self):
        public_fp = '/storage/files/3615/delicious_bookmarks-2.1.072-fx.xpi'
        guarded_fp = '/guarded-addons/3615/delicious_bookmarks-2.1.072-fx.xpi'

        # Add-on enabled, file approved
        f = File.objects.get(pk=67442)
        assert f.current_file_path.endswith(public_fp)

        # Add-on user-disabled, file approved
        f.addon.update(disabled_by_user=True)
        assert f.current_file_path.endswith(guarded_fp)
        f.addon.update(disabled_by_user=False)

        # Add-on mozilla-disabled, file approved
        f.addon.update(status=amo.STATUS_DISABLED)
        assert f.current_file_path.endswith(guarded_fp)
        f.addon.update(status=amo.STATUS_APPROVED)

        # Add-on enabled, file disabled
        f.update(status=amo.STATUS_DISABLED)
        f = File.objects.get(pk=67442)
        assert f.current_file_path.endswith(guarded_fp)

        # Add-on user-disabled, file disabled
        f.addon.update(disabled_by_user=True)
        assert f.current_file_path.endswith(guarded_fp)
        f.addon.update(disabled_by_user=False)

        # Add-on mozilla-disabled, file disabled
        f.addon.update(status=amo.STATUS_DISABLED)
        assert f.current_file_path.endswith(guarded_fp)

    def test_fallback_file_path(self):
        public_fp = '/storage/files/3615/delicious_bookmarks-2.1.072-fx.xpi'
        guarded_fp = '/guarded-addons/3615/delicious_bookmarks-2.1.072-fx.xpi'

        # Add-on enabled, file approved
        f = File.objects.get(pk=67442)
        assert f.fallback_file_path.endswith(guarded_fp)

        # Add-on user-disabled, file approved
        f.addon.update(disabled_by_user=True)
        assert f.fallback_file_path.endswith(public_fp)
        f.addon.update(disabled_by_user=False)

        # Add-on mozilla-disabled, file approved
        f.addon.update(status=amo.STATUS_DISABLED)
        assert f.fallback_file_path.endswith(public_fp)
        f.addon.update(status=amo.STATUS_APPROVED)

        # Add-on enabled, file disabled
        f.update(status=amo.STATUS_DISABLED)
        f = File.objects.get(pk=67442)
        assert f.fallback_file_path.endswith(public_fp)

        # Add-on user-disabled, file disabled
        f.addon.update(disabled_by_user=True)
        assert f.fallback_file_path.endswith(public_fp)
        f.addon.update(disabled_by_user=False)

        # Add-on mozilla-disabled, file disabled
        f.addon.update(status=amo.STATUS_DISABLED)
        assert f.fallback_file_path.endswith(public_fp)

    def test_has_been_validated_returns_false_when_no_validation(self):
        file = File()
        assert not file.has_been_validated

    def test_has_been_validated_returns_true_when_validation_exists(self):
        file = File(validation=FileValidation())
        assert file.has_been_validated


class TestTrackFileStatusChange(TestCase):

    def create_file(self, **kwargs):
        addon = Addon()
        addon.save()
        ver = Version(version='0.1')
        ver.addon = addon
        ver.save()

        f = File(**kwargs)
        f.version = ver
        f.save()

        return f

    def test_track_stats_on_new_file(self):
        with patch('olympia.files.models.track_file_status_change') as mock_:
            f = self.create_file()
        mock_.assert_called_with(f)

    def test_track_stats_on_updated_file(self):
        f = self.create_file()
        with patch('olympia.files.models.track_file_status_change') as mock_:
            f.update(status=amo.STATUS_APPROVED)

        f.reload()
        assert mock_.call_args[0][0].status == f.status

    def test_ignore_non_status_changes(self):
        f = self.create_file()
        with patch('olympia.files.models.track_file_status_change') as mock_:
            f.update(size=1024)
        assert not mock_.called, (
            'Unexpected call: {}'.format(self.mock_.call_args)
        )

    def test_increment_file_status(self):
        f = self.create_file(status=amo.STATUS_APPROVED)
        with patch('olympia.files.models.statsd.incr') as mock_incr:
            track_file_status_change(f)
        mock_incr.assert_any_call(
            'file_status_change.all.status_{}'.format(amo.STATUS_APPROVED)
        )


class TestParseXpi(TestCase):

    @classmethod
    def setUpTestData(cls):
        versions = {
            '3.0',
            '3.6.*',
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
            AppVersion.objects.create(application=amo.ANDROID.id,
                                      version=version)

    def setUp(self):
        self.user = user_factory()

    def parse(self, addon=None, filename='extension.xpi', **kwargs):
        path = 'src/olympia/files/fixtures/files/' + filename
        xpi = os.path.join(settings.ROOT, path)
        parse_addon_kwargs = {
            'user': self.user,
        }
        parse_addon_kwargs.update(**kwargs)

        with open(xpi, 'rb') as fobj:
            return parse_addon(fobj, addon, **parse_addon_kwargs)

    def test_parse_basics(self):
        # Basic test for key properties (more advanced testing is done in other
        # methods).
        expected = {
            'guid': 'guid@xpi',
            'name': 'xpi name',
            'summary': 'xpi description',
            'version': '0.1',
            'homepage': 'http://homepage.com',
            'type': 1,
            'is_webextension': False,
        }
        parsed = self.parse()
        for key, value in expected.items():
            assert parsed[key] == value

    def test_parse_minimal(self):
        # When minimal=True is passed, ensure we only have those specific
        # properties.
        expected = {
            'guid': 'guid@xpi',
            'version': '0.1',
            'type': amo.ADDON_EXTENSION,
            'is_webextension': False,
            'name': 'xpi name',
            'summary': 'xpi description',
        }
        parsed = self.parse(minimal=True)
        assert parsed == expected

    def test_parse_no_user_exception_is_thrown(self):
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(user=None)
        assert e.exception.messages[0] == 'Unexpected error.'

    def test_parse_no_user_but_minimal_is_true(self):
        # When minimal=True is passed, we can omit the user parameter.
        expected = {
            'guid': 'guid@xpi',
            'version': '0.1',
            'type': amo.ADDON_EXTENSION,
            'is_webextension': False,
            'name': 'xpi name',
            'summary': 'xpi description',
        }
        parsed = self.parse(minimal=True, user=None)
        assert parsed == expected

    def test_parse_permissions(self):
        parsed = self.parse(filename='webextension_no_id.xpi')
        assert len(parsed['permissions'])
        assert parsed['permissions'] == [
            u'http://*/*', u'https://*/*', u'bookmarks', u'made up permission',
            u'https://google.com/']

    def test_parse_optional_permissions(self):
        parsed = self.parse(filename='webextension_no_id.xpi')
        print(parsed)
        assert len(parsed['optional_permissions'])
        assert parsed['optional_permissions'] == [
            u'cookies', u'https://optional.com/']

    def test_parse_apps(self):
        expected = [Extractor.App(
            amo.FIREFOX, amo.FIREFOX.id,
            AppVersion.objects.get(
                application=amo.FIREFOX.id, version='3.0'),
            AppVersion.objects.get(
                application=amo.FIREFOX.id, version='3.6.*'))]
        assert self.parse()['apps'] == expected

    def test_no_parse_apps_error_webextension(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='57.0')
        AppVersion.objects.create(application=amo.ANDROID.id, version='57.0')
        assert self.parse(filename='webextension_with_apps_targets.xpi')

        assert self.parse(
            filename='webextension_with_apps_targets.xpi',
            minimal=False)

    def test_parse_max_star(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='56.*')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='38.0a1')
        AppVersion.objects.create(application=amo.ANDROID.id, version='56.*')
        AppVersion.objects.create(application=amo.ANDROID.id, version='38.0a1')

        # The install.rdf in jetpack_star.xpi is using '*' as the max version,
        # but it should be rewritten to '56.*'.
        expected = [
            Extractor.App(
                amo.FIREFOX, amo.FIREFOX.id,
                AppVersion.objects.get(
                    application=amo.FIREFOX.id, version='38.0a1'),
                AppVersion.objects.get(
                    application=amo.FIREFOX.id, version='56.*')),

            Extractor.App(
                amo.ANDROID, amo.ANDROID.id,
                AppVersion.objects.get(
                    application=amo.ANDROID.id, version='38.0a1'),
                AppVersion.objects.get(
                    application=amo.ANDROID.id, version='56.*'))]
        assert (
            set(self.parse(filename='jetpack_star.xpi')['apps']) ==
            set(expected))

    @mock.patch.object(amo.FIREFOX, 'guid', 'iamabadguid')
    def test_parse_apps_bad_guid(self):
        assert self.parse()['apps'] == []

    def test_guid_match(self):
        addon = Addon.objects.create(guid='guid@xpi', type=1)
        parsed = self.parse(addon)
        assert parsed['guid'] == 'guid@xpi'
        assert not parsed['is_experiment']

    def test_guid_nomatch(self):
        addon = Addon.objects.create(guid='xxx', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        assert e.exception.messages[0].startswith('The add-on ID in your')

    def test_guid_dupe(self):
        Addon.objects.create(guid='guid@xpi', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse()
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_guid_no_dupe_webextension_no_id(self):
        Addon.objects.create(guid=None, type=1)
        self.parse(filename='webextension_no_id.xpi')

    def test_guid_dupe_webextension_guid_given(self):
        Addon.objects.create(guid='@webextension-guid', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(filename='webextension.xpi')
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_guid_nomatch_webextension(self):
        addon = Addon.objects.create(
            guid='e2c45b71-6cbb-452c-97a5-7e8039cc6535', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon, filename='webextension.xpi')
        assert e.exception.messages[0].startswith('The add-on ID in your')

    def test_guid_nomatch_webextension_supports_no_guid(self):
        # addon.guid is generated if none is set originally so it doesn't
        # really matter what we set here, we allow updates to an add-on
        # with a XPI that has no id.
        addon = Addon.objects.create(
            guid='e2c45b71-6cbb-452c-97a5-7e8039cc6535', type=1)
        info = self.parse(addon, filename='webextension_no_id.xpi')
        assert info['guid'] == addon.guid

    def test_match_type(self):
        addon = Addon.objects.create(guid='guid@xpi', type=4)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        assert e.exception.messages[0] == (
            'The type (1) does not match the type of your add-on on AMO (4)')

    def test_match_type_extension_for_webextension_experiments(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='experiment_inside_webextension.xpi')
        # See #3315: webextension experiments (type 256) map to extensions.
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_experiment']
        assert not parsed['is_restart_required']

    def test_match_type_extension_for_webextensions(self):
        parsed = self.parse(filename='webextension.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_webextension']
        assert not parsed['is_restart_required']
        assert not parsed['is_experiment']

    def test_experiment_inside_webextension(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='experiment_inside_webextension.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_webextension']
        assert not parsed['is_restart_required']
        assert parsed['is_experiment']

    def test_theme_experiment_inside_webextension(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(
            filename='theme_experiment_inside_webextension.xpi')
        assert parsed['type'] == amo.ADDON_STATICTHEME
        assert parsed['is_webextension']
        assert not parsed['is_restart_required']
        assert parsed['is_experiment']

    def test_match_mozilla_signed_extension(self):
        self.user.update(email='foo@mozilla.com')
        parsed = self.parse(filename='webextension_signed_already.xpi')
        assert parsed['is_mozilla_signed_extension']

    def test_xml_for_extension(self):
        addon = Addon.objects.create(guid='guid@xpi', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon, filename='search.xml')
        assert e.exception.messages[0] == (
            'The type (4) does not match the type of your add-on on AMO (1)')

    def test_bad_zipfile(self):
        with self.assertRaises(forms.ValidationError) as e:
            # This file doesn't exist, it will raise an IOError that should
            # be caught and re-raised as a ValidationError.
            parse_addon('baxmldzip.xpi', None)
        assert e.exception.messages == ['Could not parse the manifest file.']

    def test_parse_dictionary(self):
        result = self.parse(filename='dictionary-test.xpi')
        assert result['type'] == amo.ADDON_DICT
        # We detected it as a dictionary but it's not using the explicit
        # dictionary type, so it will require a restart.
        assert result['is_restart_required']
        assert not result['strict_compatibility']

    def test_parse_dictionary_explicit_type(self):
        result = self.parse(filename='dictionary-explicit-type-test.xpi')
        assert result['type'] == amo.ADDON_DICT
        assert not result['is_restart_required']

    def test_parse_dictionary_extension(self):
        result = self.parse(filename='dictionary-extension-test.xpi')
        assert result['type'] == amo.ADDON_EXTENSION
        # It's not a real dictionary, it's an extension, so it will require a
        # restart.
        assert result['is_restart_required']

    def test_parse_no_type(self):
        result = self.parse(filename='no-type.xpi')
        assert result['type'] == amo.ADDON_EXTENSION

    def test_parse_invalid_type(self):
        result = self.parse(filename='invalid-type.xpi')
        assert result['type'] == amo.ADDON_EXTENSION

    def test_parse_langpack(self):
        # You can only submit language packs with the proper permission
        with self.assertRaises(ValidationError):
            result = self.parse(filename='webextension_langpack.xpi')

        self.grant_permission(self.user, 'LanguagePack:Submit')
        result = self.parse(filename='webextension_langpack.xpi')
        assert result['type'] == amo.ADDON_LPAPP
        assert not result['is_restart_required']

    def test_good_version_number(self):
        check_xpi_info({'guid': 'guid', 'version': '1.2a-b+32*__yeah'})
        check_xpi_info({'guid': 'guid', 'version': '1' * 32})

    def test_bad_version_number(self):
        with self.assertRaises(forms.ValidationError) as e:
            check_xpi_info({'guid': 'guid', 'version': 'bad #version'})
        msg = e.exception.messages[0]
        assert msg.startswith('Version numbers should only contain'), msg

    def test_long_version_number(self):
        with self.assertRaises(forms.ValidationError) as e:
            check_xpi_info({'guid': 'guid', 'version': '1' * 33})
        msg = e.exception.messages[0]
        assert msg == 'Version numbers should have fewer than 32 characters.'

    def test_strict_compat_undefined(self):
        result = self.parse()
        # It's a legacy extension so it will always have strict compatibility
        # enabled no matter what.
        assert result['strict_compatibility']

    def test_strict_compat_enabled(self):
        result = self.parse(filename='strict-compat.xpi')
        assert result['strict_compatibility']


class TestParseAlternateXpi(TestCase, amo.tests.AMOPaths):
    # This install.rdf is completely different from our other xpis.

    def setUp(self):
        super(TestParseAlternateXpi, self).setUp()
        for version in ('3.0', '4.0b3pre'):
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
        self.user = user_factory()

    def parse(self, filename='alt-rdf.xpi'):
        with open(self.file_fixture_path(filename), 'rb') as fobj:
            return parse_addon(fobj, user=self.user)

    def test_parse_basics(self):
        # Everything but the apps.
        exp = {
            'guid': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'name': 'Delicious Bookmarks',
            'summary': 'Access your bookmarks wherever you go and keep '
                       'them organized no matter how many you have.',
            'homepage': 'http://delicious.com',
            'type': amo.ADDON_EXTENSION,
            'version': '2.1.106'
        }
        parsed = self.parse()
        for key, value in exp.items():
            assert parsed[key] == value

    def test_parse_apps(self):
        exp = (amo.FIREFOX,
               amo.FIREFOX.id,
               AppVersion.objects.get(version='3.0'),
               AppVersion.objects.get(version='4.0b3pre'))
        assert self.parse()['apps'] == [exp]

    @mock.patch('olympia.files.utils.rdflib.Graph')
    def test_no_manifest_node(self, graph_mock):
        rdf_mock = mock.Mock()
        graph_mock.return_value.parse.return_value = rdf_mock
        rdf_mock.triples.return_value = iter([])
        rdf_mock.subjects.return_value = iter([])
        with self.assertRaises(forms.ValidationError) as e:
            self.parse()
        assert e.exception.messages == ['Could not parse the manifest file.']


class TestFileUpload(UploadTest):
    fixtures = ['base/appversion', 'base/addon_3615']

    def setUp(self):
        super(TestFileUpload, self).setUp()
        self.data = b'file contents'

    def upload(self, **params):
        # The data should be in chunks.
        data = [bytes(bytearray(s)) for s in chunked(self.data, 3)]
        return FileUpload.from_post(data, u'filenamé.xpi',
                                    len(self.data), **params)

    def test_from_post_write_file(self):
        assert storage.open(self.upload().path, 'rb').read() == self.data

    def test_from_post_filename(self):
        upload = self.upload()
        assert upload.uuid
        assert upload.name == u'{0}_filenamé.xpi'.format(
            force_text(upload.uuid.hex))

    def test_from_post_hash(self):
        hashdigest = hashlib.sha256(self.data).hexdigest()
        assert self.upload().hash == 'sha256:%s' % hashdigest

    def test_from_post_extra_params(self):
        upload = self.upload(automated_signing=True, addon_id=3615)
        assert upload.addon_id == 3615
        assert upload.automated_signing

    def test_from_post_is_one_query(self):
        with self.assertNumQueries(1):
            self.upload(automated_signing=True, addon_id=3615)

    def test_save_without_validation(self):
        upload = FileUpload.objects.create()
        assert not upload.valid

    def test_save_with_validation(self):
        upload = FileUpload.objects.create(
            validation='{"errors": 0, "metadata": {}}')
        assert upload.valid

        upload = FileUpload.objects.create(validation='{"errors": 1}')
        assert not upload.valid

        with self.assertRaises(ValueError):
            upload = FileUpload.objects.create(validation='wtf')

    def test_update_with_validation(self):
        upload = FileUpload.objects.create()
        upload.validation = '{"errors": 0, "metadata": {}}'
        upload.save()
        assert upload.valid

    def test_update_without_validation(self):
        upload = FileUpload.objects.create()
        upload.save()
        assert not upload.valid

    def test_ascii_names(self):
        upload = FileUpload.from_post(b'', u'jétpack.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(b'', u'мозила_србија-0.11-fx.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(b'', u'フォクすけといっしょ.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(b'', u'\u05d0\u05d5\u05e1\u05e3.xpi', 0)
        assert 'xpi' in upload.name

    def test_validator_sets_binary_via_extensions(self):
        validation = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "contains_binary_extension": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes",
            }
        })
        upload = self.get_upload(filename='extension.xpi',
                                 validation=validation)
        addon = Addon.objects.get(pk=3615)
        addon.update(guid='guid@xpi')
        parsed_data = parse_addon(upload, addon=addon, user=user_factory())
        file_ = File.from_upload(
            upload, addon.current_version, amo.PLATFORM_ALL.id,
            parsed_data=parsed_data)
        assert file_.binary

    def test_validator_sets_binary_via_content(self):
        validation = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "contains_binary_content": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes",
            }
        })
        upload = self.get_upload(filename='extension.xpi',
                                 validation=validation)
        addon = Addon.objects.get(pk=3615)
        addon.update(guid='guid@xpi')
        parsed_data = parse_addon(upload, addon=addon, user=user_factory())
        file_ = File.from_upload(
            upload, addon.current_version, amo.PLATFORM_ALL.id,
            parsed_data=parsed_data)
        assert file_.binary

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_warnings(self):
        data = {
            "errors": 0,
            "success": True,
            "warnings": 500,
            "notices": 0,
            "message_tree": {},
            "messages": [{
                "context": ["<code>", None],
                "description": ["Something something, see "
                                "https://bugzilla.mozilla.org/"],
                "column": 0,
                "line": 1,
                "file": "chrome/content/down.html",
                "tier": 2,
                "message": "Some warning",
                "type": "warning",
                "id": [],
                "uid": "bb9948b604b111e09dfdc42c0301fe38"}] * 12,
            "metadata": {}
        }

        upload = FileUpload(validation=json.dumps(data))
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'warning'

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_compat_errors(self):
        data = {
            "errors": 0,
            "success": True,
            "warnings": 100,
            "notices": 0,
            "message_tree": {},
            "compatibility_summary": {"errors": 100,
                                      "warnings": 0,
                                      "notices": 0},
            "messages": [
                {
                    "context": ["<code>", None],
                    "description": ["Something something, see "
                                    "https://bugzilla.mozilla.org/"],
                    "column": 0,
                    "line": 1,
                    "file": "chrome/content/down.html",
                    "tier": 2,
                    "message": "Some warning",
                    "type": "warning",
                    "compatibility_type": "warning",
                    "id": [],
                    "uid": "bb9948b604b111e09dfdc42c0301fe38"
                },
                {
                    "context": ["<code>", None],
                    "description": ["Something something, see "
                                    "https://bugzilla.mozilla.org/"],
                    "column": 0,
                    "line": 1,
                    "file": "chrome/content/down.html",
                    "tier": 2,
                    "message": "Some error",
                    "type": "warning",
                    "compatibility_type": "warning",
                    "id": [],
                    "uid": "bb9948b604b111e09dfdc42c0301fe38"
                }
            ] * 50,
            "metadata": {}
        }

        upload = FileUpload(validation=json.dumps(data))
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'warning'

        upload = FileUpload(validation=json.dumps(data),
                            compat_with_app=1)
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'error'

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_errors(self):
        data = {
            "errors": 100,
            "success": True,
            "warnings": 100,
            "notices": 0,
            "message_tree": {},
            "messages": [
                {
                    "context": ["<code>", None],
                    "description": ["Something something, see "
                                    "https://bugzilla.mozilla.org/"],
                    "column": 0,
                    "line": 1,
                    "file": "chrome/content/down.html",
                    "tier": 2,
                    "message": "Some warning",
                    "type": "warning",
                    "id": [],
                    "uid": "bb9948b604b111e09dfdc42c0301fe38"
                },
                {
                    "context": ["<code>", None],
                    "description": ["Something something, see "
                                    "https://bugzilla.mozilla.org/"],
                    "column": 0,
                    "line": 1,
                    "file": "chrome/content/down.html",
                    "tier": 2,
                    "message": "Some error",
                    "type": "error",
                    "id": [],
                    "uid": "bb9948b604b111e09dfdc42c0301fe38"
                }
            ] * 50,
            "metadata": {}
        }
        upload = FileUpload(validation=json.dumps(data))
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'error'

    def test_webextension_zip(self):
        """Test to ensure we accept ZIP uploads, but convert them into XPI
        files ASAP to keep things simple.
        """
        upload = self.get_upload(filename='webextension_no_id.zip')
        assert upload.path.endswith('.xpi')
        storage.delete(upload.path)

    def test_webextension_crx(self):
        """Test to ensure we accept CRX uploads, but convert them into XPI
        files ASAP to keep things simple.
        """
        upload = self.get_upload('webextension.crx')
        assert upload.path.endswith('.xpi')
        storage.delete(upload.path)

    def test_webextension_crx_large(self):
        """Test to ensure we accept large CRX uploads, because of how we
        write them to storage.
        """
        upload = self.get_upload('https-everywhere.crx')
        assert upload.path.endswith('.xpi')
        storage.delete(upload.path)

    def test_extension_zip(self):
        upload = self.get_upload('recurse.zip')
        assert upload.path.endswith('.xpi')
        storage.delete(upload.path)

    def test_generate_access_token_on_save(self):
        upload = FileUpload()
        assert not upload.access_token
        upload.save()
        assert upload.access_token

    def test_access_token_is_not_changed_if_already_set(self):
        access_token = 'some-access-token'
        upload = FileUpload.objects.create(access_token=access_token)
        assert upload.access_token == access_token

    def test_generate_access_token(self):
        upload = FileUpload()
        assert len(upload.generate_access_token()) == 40

    def test_get_authenticated_download_url(self):
        access_token = 'some-access-token'
        upload = FileUpload.objects.create(access_token=access_token)
        site_url = 'https://example.com'
        relative_url = reverse('files.serve_file_upload',
                               kwargs={'uuid': upload.uuid.hex})
        expected_url = '{}?access_token={}'.format(site_url + relative_url,
                                                   access_token)
        with override_settings(EXTERNAL_SITE_URL=site_url):
            assert upload.get_authenticated_download_url() == expected_url


def test_file_upload_passed_all_validations_processing():
    upload = FileUpload(valid=False, validation='')
    assert not upload.passed_all_validations


def test_file_upload_passed_all_validations_valid():
    upload = FileUpload(
        valid=True, validation=json.dumps(amo.VALIDATOR_SKELETON_RESULTS))
    assert upload.passed_all_validations


def test_file_upload_passed_all_validations_invalid():
    upload = FileUpload(
        valid=False, validation=json.dumps(amo.VALIDATOR_SKELETON_RESULTS))
    assert not upload.passed_all_validations


class TestFileFromUpload(UploadTest):

    @classmethod
    def setUpTestData(cls):
        versions = {
            '3.0',
            '3.6',
            '3.6.*',
            '4.0b6',
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        }
        for version in versions:
            AppVersion.objects.create(
                application=amo.FIREFOX.id, version=version)
            AppVersion.objects.create(
                application=amo.ANDROID.id, version=version)

    def setUp(self):
        super(TestFileFromUpload, self).setUp()
        self.platform = amo.PLATFORM_ALL.id
        self.addon = Addon.objects.create(guid='guid@xpi',
                                          type=amo.ADDON_EXTENSION,
                                          name='xxx')
        self.version = Version.objects.create(addon=self.addon)

    def upload(self, name):
        # Add in `.xpi` if the filename doesn't have a valid file extension.
        if os.path.splitext(name)[-1] not in amo.VALID_ADDON_FILE_EXTENSIONS:
            name = name + '.xpi'

        validation_data = json.dumps({
            'errors': 0,
            'warnings': 1,
            'notices': 2,
            'metadata': {},
        })
        fname = nfd_str(self.xpi_path(name))
        if not storage.exists(fname):
            with storage.open(fname, 'w') as fs:
                shutil.copyfileobj(open(fname), fs)
        data = {
            'path': force_text(fname),
            'name': force_text(name),
            'hash': 'sha256:%s' % name,
            'validation': validation_data
        }
        return FileUpload.objects.create(**data)

    def test_filename(self):
        upload = self.upload('jetpack')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == 'xxx-0.1.xpi'

    def test_filename_no_extension(self):
        upload = self.upload('jetpack')
        # Remove the extension.
        upload.name = upload.name.rsplit('.', 1)[0]
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == 'xxx-0.1.xpi'

    def test_file_validation(self):
        upload = self.upload('jetpack')
        file = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        fv = FileValidation.objects.get(file=file)
        assert json.loads(fv.validation) == json.loads(upload.validation)
        assert fv.valid
        assert fv.errors == 0
        assert fv.warnings == 1
        assert fv.notices == 2

    def test_file_hash(self):
        upload = self.upload('jetpack')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.hash.startswith('sha256:')
        assert len(file_.hash) == 64 + 7  # 64 for hash, 7 for 'sha256:'

    def test_does_not_requires_a_restart(self):
        upload = self.upload('jetpack')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert not file_.is_restart_required

    def test_does_require_a_restart(self):
        upload = self.upload('extension')
        parsed_data = parse_addon(
            upload.path, addon=self.addon, user=user_factory())
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data=parsed_data)
        assert file_.is_restart_required

    def test_utf8(self):
        upload = self.upload(u'jétpack')
        self.version.addon.name = u'jéts!'
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == u'jets-0.1.xpi'

    @mock.patch('olympia.files.models.copy_stored_file')
    def test_dont_send_both_bytes_and_str_to_copy_stored_file(
            self, copy_stored_file_mock):
        upload = self.upload(u'jétpack')
        self.version.addon.name = u'jéts!'
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == u'jets-0.1.xpi'
        expected_path_orig = force_text(upload.path)
        expected_path_dest = force_text(file_.current_file_path)
        assert copy_stored_file_mock.call_count == 1
        assert copy_stored_file_mock.call_args_list[0][0] == (
            expected_path_orig, expected_path_dest
        )

    def test_size(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.size == 2264

    def test_size_small(self):
        upload = self.upload('alt-rdf')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.size == 675

    def test_public_to_unreviewed(self):
        upload = self.upload('extension')
        self.addon.update(status=amo.STATUS_APPROVED)
        assert self.addon.status == amo.STATUS_APPROVED
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.status == amo.STATUS_AWAITING_REVIEW

    def test_file_hash_paranoia(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.hash.startswith('sha256:035ae07b4988711')

    def test_strict_compat(self):
        upload = self.upload('strict-compat')
        parsed_data = parse_addon(
            upload.path, addon=self.addon, user=user_factory())
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data=parsed_data)
        assert file_.strict_compatibility

    def test_extension_extension(self):
        upload = self.upload('extension.xpi')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xpi')

    def test_langpack_extension(self):
        upload = self.upload('webextension_langpack.xpi')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xpi')
        assert not file_.is_restart_required

    def test_search_extension(self):
        upload = self.upload('search.xml')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xml')
        assert not file_.is_restart_required

    def test_experiment(self):
        upload = self.upload('experiment_inside_webextension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_experiment': True})
        assert file_.is_experiment

    def test_not_experiment(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_experiment': False})
        assert not file_.is_experiment

    def test_mozilla_signed_extension(self):
        upload = self.upload('webextension_signed_already')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_mozilla_signed_extension': True})
        assert file_.is_mozilla_signed_extension

    def test_not_mozilla_signed_extension(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_mozilla_signed_extension': False})
        assert not file_.is_mozilla_signed_extension

    def test_webextension(self):
        upload = self.upload('webextension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert file_.is_webextension

    def test_not_webextension(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert not file_.is_experiment

    def test_permissions(self):
        upload = self.upload('webextension_no_id.xpi')
        parsed_data = parse_addon(upload, user=user_factory())
        # 5 permissions; 2 content_scripts entries.
        assert len(parsed_data['permissions']) == 5
        assert len(parsed_data['content_scripts']) == 2
        # Second content_scripts['matches'] contains two matches
        assert len(parsed_data['content_scripts'][0]['matches']) == 1
        assert len(parsed_data['content_scripts'][1]['matches']) == 2
        file_ = File.from_upload(upload, self.version, self.platform,
                                 parsed_data=parsed_data)
        permissions_list = file_.webext_permissions_list
        # 5 + 2 + 1 = 8
        assert len(permissions_list) == 8
        assert permissions_list == [
            # first 5 are 'permissions'
            u'http://*/*', u'https://*/*', 'bookmarks', 'made up permission',
            'https://google.com/',
            # last 3 are 'content_scripts' matches we treat the same
            '*://*.mozilla.org/*', '*://*.mozilla.com/*',
            'https://*.mozillians.org/*']
        assert permissions_list[0:5] == parsed_data['permissions']
        assert permissions_list[5:8] == [x for y in [
            cs['matches'] for cs in parsed_data['content_scripts']] for x in y]

    def test_optional_permissions(self):
        upload = self.upload('webextension_no_id.xpi')
        parsed_data = parse_addon(upload, user=user_factory())
        assert len(parsed_data['optional_permissions']) == 2
        file_ = File.from_upload(upload, self.version, self.platform,
                                 parsed_data=parsed_data)
        permissions_list = file_.optional_permissions_list
        assert len(permissions_list) == 2
        assert permissions_list == parsed_data['optional_permissions']

    def test_file_is_copied_to_current_path_at_upload(self):
        upload = self.upload('webextension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert os.path.exists(file_.file_path)
        assert not os.path.exists(file_.guarded_file_path)
        assert os.path.exists(file_.current_file_path)

    def test_file_is_copied_to_current_path_at_upload_if_disabled(self):
        self.addon.update(disabled_by_user=True)
        upload = self.upload('webextension')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert not os.path.exists(file_.file_path)
        assert os.path.exists(file_.guarded_file_path)
        assert os.path.exists(file_.current_file_path)


class TestZip(TestCase, amo.tests.AMOPaths):

    def test_zip_python_bug_4710(self):
        """This zip contains just one file chrome/ that we expect
        to be unzipped as a directory, not a file.
        """
        xpi = self.xpi_path('directory-test')

        # This was to work around: http://bugs.python.org/issue4710
        # which was fixed in Python 2.6.2.
        dest = tempfile.mkdtemp(dir=settings.TMP_PATH)
        zipfile.ZipFile(xpi).extractall(dest)
        assert os.path.isdir(os.path.join(dest, 'chrome'))


class TestParseSearch(TestCase, amo.tests.AMOPaths):

    def parse(self, filename='search.xml'):
        with open(self.file_fixture_path(filename)) as fobj:
            return parse_addon(fobj, user=user_factory())

    def extract(self):
        # This is the expected return value from extract_search.
        return {'url': {u'type': u'text/html', u'template':
                        u'http://www.yyy.com?q={searchTerms}'},
                'xmlns': u'http://a9.com/-/spec/opensearch/1.1/',
                'name': u'search tool',
                'description': u'Search Engine for Firefox'}

    def test_basics(self):
        # This test breaks if the day changes. Have fun with that!
        assert self.parse() == {
            'guid': None,
            'name': u'search tool',
            'is_restart_required': False,
            'is_webextension': False,
            'version': datetime.now().strftime('%Y%m%d'),
            'summary': u'Search Engine for Firefox',
            'type': amo.ADDON_SEARCH
        }

    @mock.patch('olympia.files.utils.extract_search')
    def test_extract_search_error(self, extract_mock):
        extract_mock.side_effect = Exception
        with self.assertRaises(forms.ValidationError) as e:
            self.parse()
        assert e.exception.messages[0].startswith('Could not parse ')


@mock.patch('olympia.files.utils.parse_xpi')
@mock.patch('olympia.files.utils.parse_search')
def test_parse_addon(search_mock, xpi_mock):
    user = mock.Mock()

    parse_addon('file.xpi', None, user=user)
    xpi_mock.assert_called_with('file.xpi', None, minimal=False, user=user)

    parse_addon('file.xml', None, user=user)
    search_mock.assert_called_with('file.xml', None)


def test_parse_xpi():
    """Fire.fm can sometimes give us errors.  Let's prevent that."""
    firefm = os.path.join(settings.ROOT,
                          'src/olympia/files/fixtures/files/firefm.xpi')
    rdf = parse_xpi(firefm)
    assert rdf['name'] == 'Fire.fm'
