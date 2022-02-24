import hashlib
import json
import os
import re
import tempfile
import zipfile
import shutil

from unittest import mock
from unittest.mock import patch

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

import pytest
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    user_factory,
)
from olympia.amo.utils import chunked
from olympia.applications.models import AppVersion
from olympia.files.models import (
    File,
    FileUpload,
    FileValidation,
    WebextPermission,
    nfd_str,
    track_file_status_change,
)
from olympia.files.utils import check_xpi_info, ManifestJSONExtractor, parse_addon
from olympia.users.models import UserProfile
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


class UploadMixin(amo.tests.AMOPaths):
    """
    Mixin for tests that mess with file uploads, safely using temp directories.
    """

    def setUp(self):
        create_default_webext_appversion()

    def file_path(self, *args, **kw):
        return self.file_fixture_path(*args, **kw)

    def get_upload(
        self,
        filename=None,
        abspath=None,
        validation=None,
        addon=None,
        user=None,
        version=None,
        with_validation=True,
        source=amo.UPLOAD_SOURCE_DEVHUB,
        channel=amo.RELEASE_CHANNEL_LISTED,
    ):
        if user is None:
            user = user_factory()
        with open(abspath if abspath else self.file_path(filename), 'rb') as f:
            xpi = f.read()
        with core.override_remote_addr('127.0.0.62'):
            upload = FileUpload.from_post(
                [xpi],
                filename=abspath or filename,
                size=1234,
                user=user,
                addon=addon,
                version=version,
                source=source,
                channel=channel,
            )
        if with_validation:
            # Simulate what validation does after uploading an add-on.
            upload.validation = validation or json.dumps(
                {
                    'errors': 0,
                    'warnings': 1,
                    'notices': 2,
                    'metadata': {},
                    'messages': [],
                }
            )
            upload.save()
        return upload


class TestFile(TestCase, amo.tests.AMOPaths):
    """
    Tests the methods of the File model.
    """

    fixtures = ['base/addon_3615', 'base/addon_5579']

    def test_get_absolute_url(self):
        file_ = File.objects.get(id=67442)
        url = file_.get_absolute_url()
        # Important: Fenix relies on this URL pattern to decide when to trigger
        # the add-on install flow. Changing this URL would likely break Fenix.
        expected = '/firefox/downloads/file/67442/delicious_bookmarks-2.1.072-fx.xpi'
        assert url.endswith(expected), url

    def test_get_url_path(self):
        file_ = File.objects.get(id=67442)
        assert absolutify(file_.get_url_path()) == file_.get_absolute_url()

    def test_get_url_path_attachment(self):
        file_ = File.objects.get(id=67442)
        expected = (
            '/firefox/downloads/file/67442'
            '/type:attachment/delicious_bookmarks-2.1.072-fx.xpi'
        )
        assert file_.get_url_path(attachment=True) == expected

    def test_absolute_url_attachment(self):
        file_ = File.objects.get(id=67442)
        expected = (
            'http://testserver/firefox/downloads/file/67442'
            '/type:attachment/delicious_bookmarks-2.1.072-fx.xpi'
        )
        assert file_.get_absolute_url(attachment=True) == expected

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
            with storage.open(f.current_file_path, 'w') as fi:
                fi.write('sample data\n')
            assert storage.exists(f.current_file_path)
            f.version.delete()
            assert storage.exists(f.current_file_path)
        finally:
            if storage.exists(f.current_file_path):
                storage.delete(f.current_file_path)

    def test_delete_file_path(self):
        f = File.objects.get(pk=67442)
        self.check_delete(f, f.current_file_path)

    def test_delete_no_file(self):
        # test that the file object can be deleted without the file
        # being present
        file = File.objects.get(pk=74797)
        filename = file.current_file_path
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
        f.filename = 'test_unhide_disabled_filés.xpi'
        with storage.open(f.guarded_file_path, 'wb') as fp:
            fp.write(b'some data\n')
        f.unhide_disabled_file()
        assert storage.exists(f.file_path)
        assert storage.open(f.file_path).size

    def test_latest_url(self):
        file_ = File.objects.get(id=67442)
        actual = file_.latest_xpi_url()
        assert actual == ('/firefox/downloads/latest/a3615/addon-3615-latest.xpi')

        actual = file_.latest_xpi_url(attachment=True)
        assert actual == (
            '/firefox/downloads/latest/a3615/type:attachment/addon-3615-latest.xpi'
        )

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

    def test_generate_filename_many_apps(self):
        f = File.objects.get(id=67442)
        f.version.compatible_apps = {amo.FIREFOX: None, amo.ANDROID: None}
        # After adding sorting for compatible_apps, above becomes
        # (amo.ANDROID, amo.FIREFOX) so 'an+fx' is appended to filename
        # instead of 'fx+an'
        # See: https://github.com/mozilla/addons-server/issues/3358
        assert f.generate_filename() == 'delicious_bookmarks-2.1.072-an+fx.xpi'

    def test_generate_filename_ja(self):
        f = File()
        f.version = Version(version='0.1.7')
        f.version.compatible_apps = {amo.FIREFOX: None}
        f.version.addon = Addon(name=' フォクすけ  といっしょ')
        assert f.generate_filename() == 'addon-0.1.7-fx.xpi'

    def test_generate_hash(self):
        file_ = File()
        file_.version = Version.objects.get(pk=81551)
        filename = self.xpi_path('https-everywhere.xpi')
        assert file_.generate_hash(filename).startswith('sha256:95bd414295acda29c4')

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
        return perm_a.name == perm_b.name and perm_a.description == perm_b.description

    def test_webext_permissions_list_string_only(self):
        file_ = File.objects.get(pk=67442)
        permissions = [
            'iamstring',
            'iamnutherstring',
            {'iamadict': 'hmm'},
            ['iamalistinalist', 'indeedy'],
            13,
            'laststring!',
            'iamstring',
            'iamnutherstring',
            'laststring!',
            None,
        ]
        WebextPermission.objects.create(permissions=permissions, file=file_)

        # Strings only please.No duplicates.
        assert file_.permissions == ['iamstring', 'iamnutherstring', 'laststring!']

    def test_optional_permissions_list_string_only(self):
        file_ = File.objects.get(pk=67442)
        optional_permissions = [
            'iamstring',
            'iamnutherstring',
            {'iamadict': 'hmm'},
            ['iamalistinalist', 'indeedy'],
            13,
            'laststring!',
            'iamstring',
            'iamnutherstring',
            'laststring!',
            None,
        ]
        WebextPermission.objects.create(
            optional_permissions=optional_permissions, file=file_
        )

        # Strings only please.No duplicates.
        assert file_.optional_permissions == [
            'iamstring',
            'iamnutherstring',
            'laststring!',
        ]

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
        assert not mock_.called, f'Unexpected call: {self.mock_.call_args}'

    def test_increment_file_status(self):
        f = self.create_file(status=amo.STATUS_APPROVED)
        with patch('olympia.files.models.statsd.incr') as mock_incr:
            track_file_status_change(f)
        mock_incr.assert_any_call(
            f'file_status_change.all.status_{amo.STATUS_APPROVED}'
        )


class TestParseXpi(TestCase):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX,
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id, version=version)
            AppVersion.objects.create(application=amo.ANDROID.id, version=version)

    def setUp(self):
        self.user = user_factory()

    def parse(self, addon=None, filename='webextension.xpi', **kwargs):
        path = 'src/olympia/files/fixtures/files/' + filename
        xpi = os.path.join(settings.ROOT, path)
        parse_addon_kwargs = {
            'user': self.user,
        }
        parse_addon_kwargs.update(**kwargs)

        with open(xpi, 'rb') as fobj:
            file_ = SimpleUploadedFile(filename, fobj.read())
            return parse_addon(file_, addon, **parse_addon_kwargs)

    def test_parse_basics(self):
        # Basic test for key properties (more advanced testing is done in other
        # methods).
        expected = {
            'guid': '@webextension-guid',
            'name': 'My WebExtension Addon',
            'summary': 'just a test addon with the manifest.json format',
            'version': '0.0.1',
            'homepage': None,
            'type': 1,
        }
        parsed = self.parse()
        for key, value in expected.items():
            assert parsed[key] == value

    def test_parse_minimal(self):
        # When minimal=True is passed, ensure we only have those specific
        # properties.
        expected = {
            'guid': '@webextension-guid',
            'version': '0.0.1',
            'type': amo.ADDON_EXTENSION,
            'name': 'My WebExtension Addon',
            'summary': 'just a test addon with the manifest.json format',
            'default_locale': None,
            'homepage': None,
            'manifest_version': 2,
            'install_origins': [],
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
            'guid': '@webextension-guid',
            'version': '0.0.1',
            'type': amo.ADDON_EXTENSION,
            'name': 'My WebExtension Addon',
            'summary': 'just a test addon with the manifest.json format',
            'default_locale': None,
            'homepage': None,
            'manifest_version': 2,
            'install_origins': [],
        }
        parsed = self.parse(minimal=True, user=None)
        assert parsed == expected

    def test_parse_permissions(self):
        parsed = self.parse(filename='webextension_no_id.xpi')
        assert len(parsed['permissions'])
        assert parsed['permissions'] == [
            'http://*/*',
            'https://*/*',
            'bookmarks',
            'made up permission',
            'https://google.com/',
        ]

    def test_parse_optional_permissions(self):
        parsed = self.parse(filename='webextension_no_id.xpi')
        print(parsed)
        assert len(parsed['optional_permissions'])
        assert parsed['optional_permissions'] == ['cookies', 'https://optional.com/']

    def test_parse_apps(self):
        expected = [
            ManifestJSONExtractor.App(
                amo.FIREFOX,
                amo.FIREFOX.id,
                AppVersion.objects.get(application=amo.FIREFOX.id, version='42.0'),
                AppVersion.objects.get(application=amo.FIREFOX.id, version='*'),
            ),
            ManifestJSONExtractor.App(
                amo.ANDROID,
                amo.ANDROID.id,
                AppVersion.objects.get(application=amo.ANDROID.id, version='48.0'),
                AppVersion.objects.get(application=amo.ANDROID.id, version='*'),
            ),
        ]
        assert self.parse()['apps'] == expected

    def test_no_parse_apps_error_webextension(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='57.0')
        AppVersion.objects.create(application=amo.ANDROID.id, version='57.0')
        assert self.parse(filename='webextension_with_apps_targets.xpi')

        assert self.parse(filename='webextension_with_apps_targets.xpi', minimal=False)

    def test_guid_match(self):
        addon = Addon.objects.create(guid='@webextension-guid', type=1)
        parsed = self.parse(addon)
        assert parsed['guid'] == '@webextension-guid'
        assert not parsed['is_experiment']

    def test_guid_nomatch(self):
        addon = Addon.objects.create(guid='xxx', type=1)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        assert e.exception.messages[0].startswith('The add-on ID in your')

    def test_guid_dupe(self):
        Addon.objects.create(guid='@webextension-guid', type=1)
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

    @override_switch('allow-deleted-guid-reuse', active=True)
    def test_guid_dupe_deleted_addon_allowed_if_same_author_and_switch_is_on(self):
        addon = addon_factory(guid='@webextension-guid', users=[self.user])
        addon.delete()
        data = self.parse(filename='webextension.xpi')
        assert data['guid'] == '@webextension-guid'

    def test_guid_dupe_deleted_addon_not_allowed_if_same_author_and_switch_is_off(self):
        addon = addon_factory(guid='@webextension-guid', users=[self.user])
        addon.delete()
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(filename='webextension.xpi')
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_guid_nomatch_webextension(self):
        addon = Addon.objects.create(
            guid='e2c45b71-6cbb-452c-97a5-7e8039cc6535', type=1
        )
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon, filename='webextension.xpi')
        assert e.exception.messages[0].startswith('The add-on ID in your')

    def test_guid_nomatch_webextension_supports_no_guid(self):
        # addon.guid is generated if none is set originally so it doesn't
        # really matter what we set here, we allow updates to an add-on
        # with a XPI that has no id.
        addon = Addon.objects.create(
            guid='e2c45b71-6cbb-452c-97a5-7e8039cc6535', type=1
        )
        info = self.parse(addon, filename='webextension_no_id.xpi')
        assert info['guid'] == addon.guid

    def test_match_type(self):
        addon = Addon.objects.create(guid='@webextension-guid', type=4)
        with self.assertRaises(forms.ValidationError) as e:
            self.parse(addon)
        assert e.exception.messages[0] == (
            'The type (1) does not match the type of your add-on on AMO (4)'
        )

    def test_match_type_extension_for_webextension_experiments(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='experiment_inside_webextension.xpi')
        # See #3315: webextension experiments (type 256) map to extensions.
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_experiment']

    def test_match_type_extension_for_webextensions(self):
        parsed = self.parse(filename='webextension.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert not parsed['is_experiment']

    def test_experiment_inside_webextension(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='experiment_inside_webextension.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['is_experiment']

    def test_theme_experiment_inside_webextension(self):
        self.grant_permission(self.user, 'Experiments:submit')
        parsed = self.parse(filename='theme_experiment_inside_webextension.xpi')
        assert parsed['type'] == amo.ADDON_STATICTHEME
        assert parsed['is_experiment']

    def test_match_mozilla_signed_extension(self):
        self.grant_permission(self.user, 'SystemAddon:Submit')
        parsed = self.parse(filename='webextension_signed_already.xpi')
        assert parsed['is_mozilla_signed_extension']

    def test_bad_zipfile(self):
        with self.assertRaises(forms.ValidationError) as e:
            # This file doesn't exist, it will raise an IOError that should
            # be caught and re-raised as a ValidationError.
            parse_addon('baxmldzip.xpi', None)
        assert e.exception.messages == ['Could not parse the manifest file.']

    def test_parse_langpack(self):
        # You can only submit language packs with the proper permission
        with self.assertRaises(ValidationError):
            result = self.parse(filename='webextension_langpack.xpi')

        self.grant_permission(self.user, 'LanguagePack:Submit')
        result = self.parse(filename='webextension_langpack.xpi')
        assert result['type'] == amo.ADDON_LPAPP
        assert result['strict_compatibility']

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

    def test_manifest_version(self):
        parsed = self.parse(filename='webextension_mv3.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['manifest_version'] == 3

        parsed = self.parse(filename='webextension.xpi')
        assert parsed['type'] == amo.ADDON_EXTENSION
        assert parsed['manifest_version'] == 2


class TestFileUpload(UploadMixin, TestCase):
    fixtures = ['base/appversion', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.data = b'file contents'
        self.user = UserProfile.objects.latest('pk')

    def upload(self, **params):
        # The data should be in chunks.
        data = [bytes(bytearray(s)) for s in chunked(self.data, 3)]
        params.setdefault('user', self.user)
        params.setdefault('source', amo.UPLOAD_SOURCE_DEVHUB)
        params.setdefault('channel', amo.RELEASE_CHANNEL_UNLISTED)
        return FileUpload.from_post(
            data, filename='filenamé.xpi', size=len(self.data), **params
        )

    def test_from_post_write_file(self):
        assert storage.open(self.upload().path, 'rb').read() == self.data

    def test_from_post_filename(self):
        upload = self.upload()
        assert upload.uuid
        assert upload.name == f'{force_str(upload.uuid.hex)}_filenamé.xpi'
        # Actual path on filesystem is different, fully random
        assert upload.name not in upload.path
        assert re.match(r'.*/temp/[a-f0-9]{32}\.xpi$', upload.path)

    def test_from_post_hash(self):
        hashdigest = hashlib.sha256(self.data).hexdigest()
        assert self.upload().hash == 'sha256:%s' % hashdigest

    def test_from_post_is_one_query(self):
        addon = Addon.objects.get(pk=3615)
        with self.assertNumQueries(1):
            self.upload(addon=addon)

    def test_save_without_validation(self):
        upload = FileUpload.objects.create(
            user=self.user, source=amo.UPLOAD_SOURCE_DEVHUB, ip_address='127.0.0.46'
        )
        assert not upload.valid

    def test_save_with_validation(self):
        upload = FileUpload.objects.create(
            validation='{"errors": 0, "metadata": {}}',
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            ip_address='127.0.0.46',
        )
        assert upload.valid

        upload = FileUpload.objects.create(
            validation='{"errors": 1}',
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            ip_address='127.0.0.46',
        )
        assert not upload.valid

        with self.assertRaises(ValueError):
            upload = FileUpload.objects.create(
                validation='wtf',
                user=self.user,
                source=amo.UPLOAD_SOURCE_DEVHUB,
                ip_address='127.0.0.46',
            )

    def test_update_with_validation(self):
        upload = FileUpload.objects.create(
            user=self.user, source=amo.UPLOAD_SOURCE_DEVHUB, ip_address='127.0.0.46'
        )
        upload.validation = '{"errors": 0, "metadata": {}}'
        upload.save()
        assert upload.valid

    def test_update_without_validation(self):
        upload = FileUpload.objects.create(
            user=self.user, source=amo.UPLOAD_SOURCE_DEVHUB, ip_address='127.0.0.46'
        )
        upload.save()
        assert not upload.valid

    def test_ascii_names(self):
        upload = FileUpload.from_post(
            b'',
            filename='jétpack.xpi',
            size=0,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(
            b'',
            filename='мозила_србија-0.11-fx.xpi',
            size=0,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(
            b'',
            filename='フォクすけといっしょ.xpi',
            size=0,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        assert 'xpi' in upload.name

        upload = FileUpload.from_post(
            b'',
            filename='\u05d0\u05d5\u05e1\u05e3.xpi',
            size=0,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        assert 'xpi' in upload.name

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_warnings(self):
        data = {
            'errors': 0,
            'success': True,
            'warnings': 500,
            'notices': 0,
            'message_tree': {},
            'messages': [
                {
                    'context': ['<code>', None],
                    'description': [
                        'Something something, see https://bugzilla.mozilla.org/'
                    ],
                    'column': 0,
                    'line': 1,
                    'file': 'chrome/content/down.html',
                    'tier': 2,
                    'message': 'Some warning',
                    'type': 'warning',
                    'id': [],
                    'uid': 'bb9948b604b111e09dfdc42c0301fe38',
                }
            ]
            * 12,
            'metadata': {},
        }

        upload = FileUpload(validation=json.dumps(data))
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'warning'

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_compat_errors(self):
        data = {
            'errors': 0,
            'success': True,
            'warnings': 100,
            'notices': 0,
            'message_tree': {},
            'compatibility_summary': {'errors': 100, 'warnings': 0, 'notices': 0},
            'messages': [
                {
                    'context': ['<code>', None],
                    'description': [
                        'Something something, see https://bugzilla.mozilla.org/'
                    ],
                    'column': 0,
                    'line': 1,
                    'file': 'chrome/content/down.html',
                    'tier': 2,
                    'message': 'Some warning',
                    'type': 'warning',
                    'compatibility_type': 'warning',
                    'id': [],
                    'uid': 'bb9948b604b111e09dfdc42c0301fe38',
                },
                {
                    'context': ['<code>', None],
                    'description': [
                        'Something something, see https://bugzilla.mozilla.org/'
                    ],
                    'column': 0,
                    'line': 1,
                    'file': 'chrome/content/down.html',
                    'tier': 2,
                    'message': 'Some error',
                    'type': 'warning',
                    'compatibility_type': 'warning',
                    'id': [],
                    'uid': 'bb9948b604b111e09dfdc42c0301fe38',
                },
            ]
            * 50,
            'metadata': {},
        }

        upload = FileUpload(validation=json.dumps(data))
        validation = upload.processed_validation

        assert len(validation['messages']) == 11
        assert 'truncated' in validation['messages'][0]['message']
        assert validation['messages'][0]['type'] == 'warning'

    @override_settings(VALIDATOR_MESSAGE_LIMIT=10)
    def test_limit_validator_errors(self):
        data = {
            'errors': 100,
            'success': True,
            'warnings': 100,
            'notices': 0,
            'message_tree': {},
            'messages': [
                {
                    'context': ['<code>', None],
                    'description': [
                        'Something something, see https://bugzilla.mozilla.org/'
                    ],
                    'column': 0,
                    'line': 1,
                    'file': 'chrome/content/down.html',
                    'tier': 2,
                    'message': 'Some warning',
                    'type': 'warning',
                    'id': [],
                    'uid': 'bb9948b604b111e09dfdc42c0301fe38',
                },
                {
                    'context': ['<code>', None],
                    'description': [
                        'Something something, see https://bugzilla.mozilla.org/'
                    ],
                    'column': 0,
                    'line': 1,
                    'file': 'chrome/content/down.html',
                    'tier': 2,
                    'message': 'Some error',
                    'type': 'error',
                    'id': [],
                    'uid': 'bb9948b604b111e09dfdc42c0301fe38',
                },
            ]
            * 50,
            'metadata': {},
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
        assert zipfile.is_zipfile(upload.path)
        assert upload.hash == (
            'sha256:7978b06704f4f80152f16a3ce7fe4e2590f950a99cefed15f9a8caa90fbafa23'
        )
        storage.delete(upload.path)

    def test_webextension_crx(self):
        """Test to ensure we accept CRX uploads, but convert them into XPI
        files ASAP to keep things simple.
        """
        upload = self.get_upload('webextension.crx')
        assert upload.path.endswith('.xpi')
        assert zipfile.is_zipfile(upload.path)
        assert upload.hash == (
            'sha256:6eec73112c9912e4ef63973d38ea490ccc18fa6f3cf4357fb3052a748f799f9a'
        )
        storage.delete(upload.path)

    def test_webextension_crx_large(self):
        """Test to ensure we accept large CRX uploads, because of how we
        write them to storage.
        """
        upload = self.get_upload('https-everywhere.crx')
        assert upload.path.endswith('.xpi')
        assert zipfile.is_zipfile(upload.path)
        assert upload.hash == (
            'sha256:82b71db5e6378ae888b2bcbb92fc8a24f417ef079e909db7fa51b253b13b3409'
        )
        storage.delete(upload.path)

    def test_webextension_crx_version_3(self):
        """Test to ensure we accept CRX uploads (version 3), but convert them
        into XPI files ASAP to keep things simple.
        """
        upload = self.get_upload('webextension_crx3.crx')
        assert upload.path.endswith('.xpi')
        assert zipfile.is_zipfile(upload.path)
        assert upload.hash == (
            'sha256:8640cdcbd5e85403b0a08f1c42b9dff362ceca6a92bf61f424c9764189c58950'
        )
        storage.delete(upload.path)

    def test_webextension_crx_not_a_crx(self):
        """Test to ensure we raise an explicit exception when a .crx file isn't
        a true crx (doesn't have to be caught, showing a 500 error is fine)."""
        data = b'Cr42\x02\x00\x00\x00&\x01\x00\x00\x00\x01\x00\x00'
        upload = FileUpload.from_post(
            [data],
            filename='test.crx',
            size=1234,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        # We couldn't convert it as it's an invalid or unsupported crx, so
        # re storing the file as-is.
        assert upload.hash == 'sha256:%s' % hashlib.sha256(data).hexdigest()
        storage.delete(upload.path)

    def test_webextension_crx_version_unsupported(self):
        """Test to ensure we only support crx versions 2 and 3 and raise an
        explicit exception otherwise (doesn't have to be caught, showing a 500
        error is fine)."""
        data = b'Cr24\x04\x00\x00\x00&\x01\x00\x00\x00\x01\x00\x00'
        upload = FileUpload.from_post(
            [data],
            filename='test.crx',
            size=1234,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        # We couldn't convert it as it's an invalid or unsupported crx, so
        # re storing the file as-is.
        assert upload.hash == 'sha256:%s' % hashlib.sha256(data).hexdigest()
        storage.delete(upload.path)

    def test_webextension_crx_version_cant_unpack(self):
        """Test to ensure we raise an explicit exception when we can't unpack
        a crx (doesn't have to be caught, showing a 500 error is fine)."""
        data = b'Cr24\x02\x00\x00\x00&\x00\x00\x00\x01\x00\x00'
        upload = FileUpload.from_post(
            [data],
            filename='test.crx',
            size=1234,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        # We're storing the file as-is.
        assert upload.hash == 'sha256:%s' % hashlib.sha256(data).hexdigest()
        storage.delete(upload.path)

    def test_extension_zip(self):
        upload = self.get_upload('recurse.zip')
        assert upload.path.endswith('.xpi')
        assert zipfile.is_zipfile(upload.path)
        storage.delete(upload.path)

    def test_generate_access_token_on_save(self):
        upload = FileUpload(
            user=self.user, source=amo.UPLOAD_SOURCE_DEVHUB, ip_address='127.0.0.46'
        )
        assert not upload.access_token
        upload.save()
        assert upload.access_token

    def test_access_token_is_not_changed_if_already_set(self):
        access_token = 'some-access-token'
        upload = FileUpload.objects.create(
            access_token=access_token,
            user=UserProfile.objects.latest('pk'),
            ip_address='127.0.0.45',
            source=amo.UPLOAD_SOURCE_DEVHUB,
        )
        assert upload.access_token == access_token

    def test_generate_access_token(self):
        upload = FileUpload()
        assert len(upload.generate_access_token()) == 40

    def test_get_authenticated_download_url(self):
        access_token = 'some-access-token'
        upload = FileUpload.objects.create(
            access_token=access_token,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            ip_address='127.0.0.48',
        )
        site_url = 'https://example.com'
        relative_url = reverse(
            'files.serve_file_upload', kwargs={'uuid': upload.uuid.hex}
        )
        expected_url = '{}?access_token={}'.format(
            site_url + relative_url, access_token
        )
        with override_settings(EXTERNAL_SITE_URL=site_url):
            assert upload.get_authenticated_download_url() == expected_url


def test_file_upload_passed_all_validations_processing():
    upload = FileUpload(valid=False, validation='')
    assert not upload.passed_all_validations


def test_file_upload_passed_all_validations_valid():
    upload = FileUpload(
        valid=True, validation=json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
    )
    assert upload.passed_all_validations


def test_file_upload_passed_all_validations_invalid():
    upload = FileUpload(
        valid=False, validation=json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
    )
    assert not upload.passed_all_validations


class TestFileFromUpload(UploadMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.create(
            guid='@webextension-guid', type=amo.ADDON_EXTENSION, name='xxx'
        )
        self.version = Version.objects.create(addon=self.addon)
        patcher = mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
        self.addCleanup(patcher.stop)
        patcher.start()

    def upload(self, name):
        validation_data = json.dumps(
            {
                'errors': 0,
                'warnings': 1,
                'notices': 2,
                'metadata': {},
            }
        )
        fname = nfd_str(self.xpi_path(name))
        if not self.root_storage.exists(fname):
            with self.root_storage.open(fname, 'w') as fs:
                shutil.copyfileobj(open(fname), fs)
        data = {
            'path': force_str(fname),
            'name': force_str(name),
            'hash': 'sha256:%s' % name,
            'validation': validation_data,
            'source': amo.UPLOAD_SOURCE_DEVHUB,
            'ip_address': '127.0.0.50',
            'user': user_factory(),
        }
        return FileUpload.objects.create(**data)

    def test_filename(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename == 'xxx-0.1.xpi'

    def test_filename_no_extension(self):
        upload = self.upload('webextension.xpi')
        # Remove the extension.
        upload.name = upload.name.rsplit('.', 1)[0]
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename == 'xxx-0.1.xpi'

    def test_file_validation(self):
        upload = self.upload('webextension.xpi')
        file = File.from_upload(upload, self.version, parsed_data={})
        fv = FileValidation.objects.get(file=file)
        assert json.loads(fv.validation) == json.loads(upload.validation)
        assert fv.valid
        assert fv.errors == 0
        assert fv.warnings == 1
        assert fv.notices == 2

    def test_file_hash(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.hash.startswith('sha256:')
        assert len(file_.hash) == 64 + 7  # 64 for hash, 7 for 'sha256:'

    def test_utf8(self):
        upload = self.upload('wébextension.xpi')
        self.version.addon.name = 'jéts!'
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename == 'jets-0.1.xpi'

    @mock.patch('olympia.amo.utils.SafeStorage.copy_stored_file')
    def test_dont_send_both_bytes_and_str_to_copy_stored_file(
        self, copy_stored_file_mock
    ):
        upload = self.upload('wébextension.xpi')
        self.version.addon.name = 'jéts!'
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename == 'jets-0.1.xpi'
        expected_path_orig = force_str(upload.path)
        expected_path_dest = force_str(file_.current_file_path)
        assert copy_stored_file_mock.call_count == 1
        assert copy_stored_file_mock.call_args_list[0][0] == (
            expected_path_orig,
            expected_path_dest,
        )

    def test_size(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.size == 537

    def test_public_to_unreviewed(self):
        upload = self.upload('webextension.xpi')
        self.addon.update(status=amo.STATUS_APPROVED)
        assert self.addon.status == amo.STATUS_APPROVED
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.status == amo.STATUS_AWAITING_REVIEW

    def test_file_hash_paranoia(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.hash.startswith('sha256:79ff4a97e898d80')

    def test_extension_extension(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename.endswith('.xpi')

    def test_langpack_extension(self):
        upload = self.upload('webextension_langpack.xpi')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.filename.endswith('.xpi')

    def test_experiment(self):
        upload = self.upload('experiment_inside_webextension')
        file_ = File.from_upload(
            upload, self.version, parsed_data={'is_experiment': True}
        )
        assert file_.is_experiment

    def test_not_experiment(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(
            upload, self.version, parsed_data={'is_experiment': False}
        )
        assert not file_.is_experiment

    def test_mozilla_signed_extension(self):
        upload = self.upload('webextension_signed_already')
        file_ = File.from_upload(
            upload,
            self.version,
            parsed_data={'is_mozilla_signed_extension': True},
        )
        assert file_.is_mozilla_signed_extension

    def test_not_mozilla_signed_extension(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(
            upload,
            self.version,
            parsed_data={'is_mozilla_signed_extension': False},
        )
        assert not file_.is_mozilla_signed_extension

    def test_webextension_mv2(self):
        upload = self.upload('webextension')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert file_.manifest_version == 2

    def test_webextension_mv3(self):
        upload = self.upload('webextension_mv3.xpi')
        file_ = File.from_upload(
            upload, self.version, parsed_data={'manifest_version': 3}
        )
        assert file_.manifest_version == 3

    def test_permissions(self):
        upload = self.upload('webextension_no_id.xpi')
        with self.root_storage.open(upload.path, 'rb') as upload_file:
            parsed_data = parse_addon(upload_file, user=user_factory())
        # 5 permissions; 2 content_scripts entries.
        assert len(parsed_data['permissions']) == 5
        assert len(parsed_data['content_scripts']) == 2
        # Second content_scripts['matches'] contains two matches
        assert len(parsed_data['content_scripts'][0]['matches']) == 1
        assert len(parsed_data['content_scripts'][1]['matches']) == 2
        file_ = File.from_upload(upload, self.version, parsed_data=parsed_data)
        permissions_list = file_.permissions
        # 5 + 2 + 1 = 8
        assert len(permissions_list) == 8
        assert permissions_list == [
            # first 5 are 'permissions'
            'http://*/*',
            'https://*/*',
            'bookmarks',
            'made up permission',
            'https://google.com/',
            # last 3 are 'content_scripts' matches we treat the same
            '*://*.mozilla.org/*',
            '*://*.mozilla.com/*',
            'https://*.mozillians.org/*',
        ]
        assert permissions_list[0:5] == parsed_data['permissions']
        assert permissions_list[5:8] == [
            x
            for y in [cs['matches'] for cs in parsed_data['content_scripts']]
            for x in y
        ]

    def test_optional_permissions(self):
        upload = self.upload('webextension_no_id.xpi')
        with self.root_storage.open(upload.path, 'rb') as upload_file:
            parsed_data = parse_addon(upload_file, user=user_factory())
        assert len(parsed_data['optional_permissions']) == 2
        file_ = File.from_upload(upload, self.version, parsed_data=parsed_data)
        permissions_list = file_.optional_permissions
        assert len(permissions_list) == 2
        assert permissions_list == parsed_data['optional_permissions']

    def test_file_is_copied_to_current_path_at_upload(self):
        upload = self.upload('webextension')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert os.path.exists(file_.file_path)
        assert not os.path.exists(file_.guarded_file_path)
        assert os.path.exists(file_.current_file_path)

    def test_file_is_copied_to_current_path_at_upload_if_disabled(self):
        self.addon.update(disabled_by_user=True)
        upload = self.upload('webextension')
        file_ = File.from_upload(upload, self.version, parsed_data={})
        assert not os.path.exists(file_.file_path)
        assert os.path.exists(file_.guarded_file_path)
        assert os.path.exists(file_.current_file_path)

    def test_permission_enabler_site_permissions(self):
        upload = self.upload('webextension.xpi')
        file_ = File.from_upload(
            upload,
            self.version,
            parsed_data={
                'type': amo.ADDON_SITE_PERMISSION,
                'site_permissions': ['one', 'two'],
            },
        )
        site_permissions = file_._site_permissions
        assert site_permissions.pk
        assert site_permissions.permissions == ['one', 'two']


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


@mock.patch('olympia.files.utils.parse_xpi')
def test_parse_addon(xpi_mock):
    user = mock.Mock()

    parse_addon('file.xpi', None, user=user)
    xpi_mock.assert_called_with('file.xpi', None, minimal=False, user=user)
