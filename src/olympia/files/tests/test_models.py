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
from django.test.utils import override_settings

import mock
import pytest

from mock import patch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.utils import chunked
from olympia.applications.models import AppVersion
from olympia.files.models import (
    EXTENSIONS, File, FileUpload, FileValidation, Permission, WebextPermission,
    WebextPermissionDescription, nfd_str, track_file_status_change)
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

    def get_upload(self, filename=None, abspath=None, validation=None):
        xpi = open(abspath if abspath else self.file_path(filename)).read()
        upload = FileUpload.from_post([xpi], filename=abspath or filename,
                                      size=1234)
        # Simulate what fetch_manifest() does after uploading an app.
        upload.validation = (validation or
                             json.dumps(dict(errors=0, warnings=1, notices=2,
                                             metadata={}, messages=[])))
        upload.save()
        return upload


class TestFile(TestCase, amo.tests.AMOPaths):
    """
    Tests the methods of the File model.
    """
    fixtures = ['base/addon_3615', 'base/addon_5579']

    def test_get_absolute_url(self):
        f = File.objects.get(id=67442)
        url = f.get_absolute_url(src='src')
        expected = ('/firefox/downloads/file/67442/'
                    'delicious_bookmarks-2.1.072-fx.xpi?src=src')
        assert url.endswith(expected), url

    def test_get_url_path(self):
        file_ = File.objects.get(id=67442)
        assert file_.get_url_path('src') == \
            file_.get_absolute_url(src='src')

    def test_get_url_path_attachment(self):
        file_ = File.objects.get(id=67442)
        expected = ('http://testserver/firefox/downloads/file/67442'
                    '/type:attachment/delicious_bookmarks-2.1.072-fx.xpi'
                    '?src=src')
        assert file_.get_url_path('src', attachment=True) == expected

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
        f.status = amo.STATUS_PUBLIC
        f.save()
        assert not hide_mock.called

        f.status = amo.STATUS_DISABLED
        f.save()
        assert hide_mock.called

    @mock.patch('olympia.files.models.File.unhide_disabled_file')
    def test_unhide_on_enable(self, unhide_mock):
        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_PUBLIC
        f.save()
        assert not unhide_mock.called

        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_DISABLED
        f.save()
        assert not unhide_mock.called

        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_PUBLIC
        f.save()
        assert unhide_mock.called

    def test_unhide_disabled_files(self):
        f = File.objects.get(pk=67442)
        f.status = amo.STATUS_PUBLIC
        with storage.open(f.guarded_file_path, 'wb') as fp:
            fp.write('some data\n')
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

    def test_eula_url(self):
        f = File.objects.get(id=67442)
        assert f.eula_url() == '/en-US/firefox/addon/3615/eula/67442'

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
        f.version._compatible_apps = {amo.THUNDERBIRD: None, amo.FIREFOX: None}
        # After adding sorting for compatible_apps, above becomes
        # (amo.FIREFOX, amo.THUNDERBIRD) so 'fx+tb' is appended to filename
        # instead of 'tb+fx'
        # See: https://github.com/mozilla/addons-server/issues/3358
        assert f.generate_filename() == 'delicious_bookmarks-2.1.072-fx+tb.xpi'

    def test_generate_filename_ja(self):
        f = File()
        f.version = Version(version='0.1.7')
        f.version._compatible_apps = {amo.FIREFOX: None}
        f.version.addon = Addon(name=u' フォクすけ  といっしょ')
        assert f.generate_filename() == 'addon-0.1.7-fx.xpi'

    def clean_files(self, f):
        if not storage.exists(f.file_path):
            with storage.open(f.file_path, 'w') as fp:
                fp.write('sample data\n')

    def test_generate_hash(self):
        f = File()
        f.version = Version.objects.get(pk=81551)
        fn = self.xpi_path('delicious_bookmarks-2.1.106-fx')
        assert f.generate_hash(fn).startswith('sha256:fd277d45ab44f6240e')

    def test_addon(self):
        f = File.objects.get(pk=67442)
        addon_id = f.version.addon_id
        addon = Addon.objects.get(pk=addon_id)
        addon.update(status=amo.STATUS_DELETED)
        assert f.addon.id == addon_id

    def _cmp_permission(self, perm_a, perm_b):
        return (perm_a.name == perm_b.name and
                perm_a.description == perm_b.description)

    def test_webext_permissions_order(self):
        perm_list = [u'tabs', u'bookmarks', u'nativeMessaging',
                     u'made up permission', u'https://google.com/']
        WebextPermissionDescription.objects.create(
            name=u'bookmarks', description=u'Read and modify bookmarks')
        WebextPermissionDescription.objects.create(
            name=u'tabs', description=u'Access browser tabs')
        WebextPermissionDescription.objects.create(
            name=u'nativeMessaging',
            description=u'Exchange messages with programs other than Firefox')

        result = [
            # First match urls for specified site(s).
            Permission('single-match',
                       'Access your data for https://google.com/'),
            # Then nativeMessaging, if specified
            Permission(u'nativeMessaging',
                       u'Exchange messages with programs other than Firefox'),
            # Then any other known permission(s).
            Permission(u'bookmarks',
                       u'Read and modify bookmarks'),
            Permission(u'tabs',
                       u'Access browser tabs'),
        ]

        file_ = File.objects.get(pk=67442)
        file_.webext_permissions_list = perm_list

        # Check the order
        assert len(file_.webext_permissions) == len(result)
        assert all(map(self._cmp_permission, result,
                       file_.webext_permissions))

        # Check the order isn't dependent on the order in the manifest
        file_.webext_permissions_list.reverse()
        assert all(map(self._cmp_permission, result,
                       file_.webext_permissions))

        # Unknown permission strings aren't included.
        assert ((u'made up permission', u'made up permission')
                not in file_.webext_permissions)

    def test_webext_permissions_match_urls(self):
        file_ = File.objects.get(pk=67442)
        # Multiple urls for specified sites should be grouped together
        file_.webext_permissions_list = [
            u'https://mozilla.org/', u'https://mozillians.org/']

        assert len(file_.webext_permissions) == 1
        perm = file_.webext_permissions[0]
        assert perm.name == u'multiple-match'
        assert perm.description == (
            u'<details><summary>Access your data on the following websites:'
            u'</summary><ul><li>https://mozilla.org/</li>'
            u'<li>https://mozillians.org/</li></ul></details>')

        file_.webext_permissions_list += [u'http://*/*', u'<all_urls>']
        # Match-all patterns should override the specific sites
        assert len(file_.webext_permissions) == 1
        assert file_.webext_permissions[0] == (
            WebextPermissionDescription.ALL_URLS_PERMISSION)

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
            f.update(status=amo.STATUS_PUBLIC)

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
        f = self.create_file(status=amo.STATUS_PUBLIC)
        with patch('olympia.files.models.statsd.incr') as mock_incr:
            track_file_status_change(f)
        mock_incr.assert_any_call(
            'file_status_change.all.status_{}'.format(amo.STATUS_PUBLIC)
        )

    def test_increment_jetpack_sdk_only_status(self):
        f = self.create_file(
            status=amo.STATUS_PUBLIC,
            jetpack_version='1.0',
            is_restart_required=False,
            requires_chrome=False,
        )
        with patch('olympia.files.models.statsd.incr') as mock_incr:
            track_file_status_change(f)
        mock_incr.assert_any_call(
            'file_status_change.jetpack_sdk_only.status_{}'
            .format(amo.STATUS_PUBLIC)
        )


class TestParseXpi(TestCase):

    def setUp(self):
        super(TestParseXpi, self).setUp()
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
        self.user = user_factory()

    def parse(self, addon=None, filename='extension.xpi', **kwargs):
        path = 'src/olympia/files/fixtures/files/' + filename
        xpi = os.path.join(settings.ROOT, path)
        parse_addon_kwargs = {
            'user': self.user,
        }
        parse_addon_kwargs.update(**kwargs)

        with open(xpi) as fobj:
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
        }
        parsed = self.parse(minimal=True, user=None)
        assert parsed == expected

    def test_parse_permissions(self):
        parsed = self.parse(filename='webextension_no_id.xpi')
        assert len(parsed['permissions'])
        assert parsed['permissions'] == [
            u'http://*/*', u'https://*/*', u'bookmarks', u'made up permission',
            u'https://google.com/']

    def test_parse_apps(self):
        expected = [Extractor.App(
            amo.FIREFOX, amo.FIREFOX.id,
            AppVersion.objects.get(version='3.0'),
            AppVersion.objects.get(version='3.6.*'))]
        assert self.parse()['apps'] == expected

    def test_parse_apps_error_webextension(self):
        AppVersion.objects.all().delete()
        with self.assertRaises(forms.ValidationError) as e:
            assert self.parse(filename='webextension_with_apps_targets.xpi')
        assert e.exception.messages[0].startswith('Cannot find min/max vers')

        with self.assertRaises(forms.ValidationError) as e:
            assert self.parse(
                filename='webextension_with_apps_targets.xpi',
                minimal=False)
        assert e.exception.messages[0].startswith('Cannot find min/max vers')

        # When minimal=True is passed, we don't do validation...
        expected = {
            'guid': '@webext-with-targets',
            'type': amo.ADDON_EXTENSION,
            'version': '1.0',
            'is_webextension': True,
        }
        parsed = self.parse(
            filename='webextension_with_apps_targets.xpi',
            minimal=True)
        assert parsed == expected

    def test_parse_max_star(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='56.*')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='*')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='38.0a1')
        AppVersion.objects.create(application=amo.ANDROID.id, version='*')
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

    def test_parse_apps_bad_appver(self):
        AppVersion.objects.all().delete()
        assert self.parse()['apps'] == []

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
        assert e.exception.messages[0].startswith(
            '<em:type> in your install.rdf')

    def test_match_type_extension_for_telemetry_experiments(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='telemetry_experiment.xpi')
        # See bug 1220097: telemetry experiments (type 128) map to extensions.
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_experiment']
        assert not parsed['is_restart_required']

    def test_match_type_extension_for_webextension_experiments(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='webextension_experiment.xpi')
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

    def test_match_mozilla_signed_extension(self):
        self.user.update(email='foo@mozilla.com')
        parsed = self.parse(filename='webextension_signed_already.xpi')
        assert parsed['is_mozilla_signed_extension']

    def test_xml_for_extension(self):
        addon = Addon.objects.create(guid='guid@xpi', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon, filename='search.xml')
        assert e.exception.messages[0].startswith(
            '<em:type> in your install.rdf')

    def test_unknown_app(self):
        data = self.parse(filename='theme-invalid-app.jar')
        assert data['apps'] == []

    def test_bad_zipfile(self):
        with self.assertRaises(forms.ValidationError) as e:
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

    def test_parse_jar(self):
        result = self.parse(filename='theme.jar')
        assert result['type'] == amo.ADDON_THEME

    def test_parse_theme_by_type(self):
        result = self.parse(filename='theme-type.xpi')
        assert result['type'] == amo.ADDON_THEME

    def test_parse_theme_with_internal_name(self):
        result = self.parse(filename='theme-internal-name.xpi')
        assert result['type'] == amo.ADDON_THEME

    def test_parse_no_type(self):
        result = self.parse(filename='no-type.xpi')
        assert result['type'] == amo.ADDON_EXTENSION

    def test_parse_invalid_type(self):
        result = self.parse(filename='invalid-type.xpi')
        assert result['type'] == amo.ADDON_EXTENSION

    def test_parse_langpack(self):
        result = self.parse(filename='langpack.xpi')
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
        with open(self.file_fixture_path(filename)) as fobj:
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
        self.data = 'file contents'

    def upload(self, **params):
        # The data should be in chunks.
        data = [''.join(x) for x in chunked(self.data, 3)]
        return FileUpload.from_post(data, 'filename.xpi',
                                    len(self.data), **params)

    def test_from_post_write_file(self):
        assert storage.open(self.upload().path).read() == self.data

    def test_from_post_filename(self):
        upload = self.upload()
        assert upload.uuid
        assert upload.name == '{0}_filename.xpi'.format(upload.uuid.hex)

    def test_from_post_hash(self):
        hash = hashlib.sha256(self.data).hexdigest()
        assert self.upload().hash == 'sha256:%s' % hash

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
        upload = FileUpload.from_post('', u'jétpack.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post('', u'мозила_србија-0.11-fx.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post('', u'フォクすけといっしょ.xpi', 0)
        assert 'xpi' in upload.name

        upload = FileUpload.from_post('', u'\u05d0\u05d5\u05e1\u05e3.xpi', 0)
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
            upload, addon.current_version, amo.PLATFORM_LINUX.id,
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
            upload, addon.current_version, amo.PLATFORM_LINUX.id,
            parsed_data=parsed_data)
        assert file_.binary

    def test_validator_sets_require_chrome(self):
        validation = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes",
                "requires_chrome": True
            }
        })
        upload = self.get_upload(filename='extension.xpi',
                                 validation=validation)
        addon = Addon.objects.get(pk=3615)
        addon.update(guid='guid@xpi')
        parsed_data = parse_addon(upload, addon=addon, user=user_factory())
        file_ = File.from_upload(
            upload, addon.current_version, amo.PLATFORM_LINUX.id,
            parsed_data=parsed_data)
        assert file_.requires_chrome

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

    def setUp(self):
        super(TestFileFromUpload, self).setUp()
        for version in ('3.0', '3.6', '3.6.*', '4.0b6'):
            AppVersion(application=amo.FIREFOX.id, version=version).save()
        self.platform = amo.PLATFORM_MAC.id
        self.addon = Addon.objects.create(guid='guid@xpi',
                                          type=amo.ADDON_EXTENSION,
                                          name='xxx')
        self.version = Version.objects.create(addon=self.addon)

    def upload(self, name):
        # Add in `.xpi` if the filename doesn't have a valid file extension.
        if os.path.splitext(name)[-1] not in EXTENSIONS:
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
            'path': fname,
            'name': name,
            'hash': 'sha256:%s' % name,
            'validation': validation_data
        }
        return FileUpload.objects.create(**data)

    def test_jetpack_version(self):
        upload = self.upload('jetpack')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        file_ = File.objects.get(id=file_.id)
        assert file_.jetpack_version == '1.0b4'

    def test_jetpack_with_invalid_json(self):
        upload = self.upload('jetpack_invalid')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        file_ = File.objects.get(id=file_.id)
        assert file_.jetpack_version is None

    def test_filename(self):
        upload = self.upload('jetpack')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == 'xxx-0.1-mac.xpi'

    def test_filename_no_extension(self):
        upload = self.upload('jetpack')
        # Remove the extension.
        upload.name = upload.name.rsplit('.', 1)[0]
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename == 'xxx-0.1-mac.xpi'

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
        assert file_.filename == u'jets-0.1-mac.xpi'

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
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert self.addon.status == amo.STATUS_PUBLIC
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

    def test_theme_extension(self):
        upload = self.upload('theme.jar')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xpi')

    def test_extension_extension(self):
        upload = self.upload('extension.xpi')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xpi')

    def test_langpack_extension(self):
        upload = self.upload('langpack.xpi')
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

    def test_multi_package(self):
        upload = self.upload('multi-package')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_multi_package': True})
        assert file_.is_multi_package

    def test_not_multi_package(self):
        upload = self.upload('extension')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert not file_.is_multi_package

    def test_experiment(self):
        upload = self.upload('telemetry_experiment')
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

    def test_webextension_zip(self):
        """Test to ensure we accept ZIP uploads, but convert them into XPI
        files ASAP to keep things simple.
        """
        upload = self.upload('webextension.zip')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert file_.filename.endswith('.xpi')
        assert file_.is_webextension
        storage.delete(upload.path)

    def test_webextension_crx(self):
        """Test to ensure we accept CRX uploads, but convert them into XPI
        files ASAP to keep things simple.
        """
        upload = self.upload('webextension.crx')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert file_.filename.endswith('.xpi')
        assert file_.is_webextension
        storage.delete(upload.path)

    def test_webextension_crx_large(self):
        """Test to ensure we accept large CRX uploads, because of how we
        write them to storage.
        """
        upload = self.upload('https-everywhere.crx')
        file_ = File.from_upload(
            upload, self.version, self.platform,
            parsed_data={'is_webextension': True})
        assert file_.filename.endswith('.xpi')
        assert file_.is_webextension
        storage.delete(upload.path)

    def test_extension_zip(self):
        upload = self.upload('recurse.zip')
        file_ = File.from_upload(
            upload, self.version, self.platform, parsed_data={})
        assert file_.filename.endswith('.xpi')
        assert not file_.is_webextension
        storage.delete(upload.path)

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

    parse_addon('file.jar', None, user=user)
    xpi_mock.assert_called_with('file.jar', None, minimal=False, user=user)


def test_parse_xpi():
    """Fire.fm can sometimes give us errors.  Let's prevent that."""
    firefm = os.path.join(settings.ROOT,
                          'src/olympia/files/fixtures/files/firefm.xpi')
    rdf = parse_xpi(open(firefm))
    assert rdf['name'] == 'Fire.fm'


class LanguagePackBase(UploadTest):
    fixtures = ['base/appversion']

    def setUp(self):
        super(LanguagePackBase, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_LPAPP)
        self.platform = amo.PLATFORM_ALL.id
        self.version = Version.objects.create(addon=self.addon)
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.addon._current_version = self.version


class TestLanguagePack(LanguagePackBase):

    def file_create(self, path):
        return (File.objects.create(platform=self.platform,
                                    version=self.version,
                                    filename=self.xpi_path(path)))

    def test_extract(self):
        obj = self.file_create('langpack-localepicker')
        assert 'title=Select a language' in obj.get_localepicker()

    def test_extract_no_chrome_manifest(self):
        obj = self.file_create('langpack')
        assert obj.get_localepicker() == ''

    def test_zip_invalid(self):
        obj = self.file_create('search.xml')
        assert obj.get_localepicker() == ''

    @mock.patch('olympia.files.utils.SafeZip.read')
    def test_no_locale_browser(self, read_mock):
        read_mock.return_value = 'some garbage'
        obj = self.file_create('langpack-localepicker')
        assert obj.get_localepicker() == ''

    @mock.patch('olympia.files.utils.SafeZip.read')
    def test_corrupt_locale_browser_path(self, read_mock):
        read_mock.return_value = 'locale browser de woot?!'
        obj = self.file_create('langpack-localepicker')
        assert obj.get_localepicker() == ''
        read_mock.return_value = 'locale browser de woo:t?!as'
        # Result should be 'locale browser de woo:t?!as', but we have caching.
        assert obj.get_localepicker() == ''

    @mock.patch('olympia.files.utils.SafeZip.read')
    def test_corrupt_locale_browser_data(self, read_mock):
        read_mock.return_value = 'locale browser de jar:install.rdf!foo'
        obj = self.file_create('langpack-localepicker')
        assert obj.get_localepicker() == ''

    def test_hits_cache(self):
        obj = self.file_create('langpack-localepicker')
        assert 'title=Select a language' in obj.get_localepicker()
        obj.update(filename='garbage')
        assert 'title=Select a language' in obj.get_localepicker()

    @mock.patch('olympia.files.models.File.get_localepicker')
    def test_cache_on_create(self, get_localepicker):
        self.file_create('langpack-localepicker')
        assert get_localepicker.called

    @mock.patch('olympia.files.models.File.get_localepicker')
    def test_cache_not_on_create(self, get_localepicker):
        self.addon.update(type=amo.ADDON_DICT)
        self.file_create('langpack-localepicker')
        assert not get_localepicker.called
