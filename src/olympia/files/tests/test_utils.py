# -*- coding: utf-8 -*-
import json
import os
import shutil
import tempfile
import time
import zipfile
import multiprocessing
import contextlib

from unittest import mock

from django import forms
from django.conf import settings
from django.forms import ValidationError
from django.test.utils import override_settings

import lxml
import pytest

from defusedxml.common import EntitiesForbidden, NotSupportedError
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.tests.test_helpers import get_addon_file
from olympia.applications.models import AppVersion
from olympia.files import utils


pytestmark = pytest.mark.django_db


def _touch(fname):
    open(fname, 'a').close()
    os.utime(fname, None)


class AppVersionsMixin(object):
    @classmethod
    def setUpTestData(cls):
        cls.create_webext_default_versions()

    @classmethod
    def create_appversion(cls, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id,
                                         version=version)

    @classmethod
    def create_webext_default_versions(cls):
        cls.create_appversion('firefox', '36.0')  # Incompatible with webexts.
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MAX_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID)
        cls.create_appversion(
            'android', amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        cls.create_appversion(
            'android', amo.DEFAULT_WEBEXT_MAX_VERSION)
        cls.create_appversion(
            'firefox', amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        cls.create_appversion(
            'android', amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)


class TestExtractor(AppVersionsMixin, TestCase):

    def test_no_manifest(self):
        fake_zip = utils.make_xpi({'dummy': 'dummy'})

        with self.assertRaises(utils.NoManifestFound) as exc:
            utils.Extractor.parse(fake_zip)
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == (
            'No install.rdf or manifest.json found')

    @mock.patch('olympia.files.utils.ManifestJSONExtractor')
    @mock.patch('olympia.files.utils.RDFExtractor')
    def test_parse_install_rdf(self, rdf_extractor, manifest_json_extractor):
        fake_zip = utils.make_xpi({'install.rdf': ''})
        utils.Extractor.parse(fake_zip)
        assert rdf_extractor.called
        assert not manifest_json_extractor.called

    @mock.patch('olympia.files.utils.ManifestJSONExtractor')
    @mock.patch('olympia.files.utils.RDFExtractor')
    def test_ignore_package_json(self, rdf_extractor, manifest_json_extractor):
        # Previously we preferred `package.json` to `install.rdf` which
        # we don't anymore since
        # https://github.com/mozilla/addons-server/issues/2460
        fake_zip = utils.make_xpi({'install.rdf': '', 'package.json': ''})
        utils.Extractor.parse(fake_zip)
        assert rdf_extractor.called
        assert not manifest_json_extractor.called

    @mock.patch('olympia.files.utils.ManifestJSONExtractor')
    @mock.patch('olympia.files.utils.RDFExtractor')
    def test_parse_manifest_json(self, rdf_extractor, manifest_json_extractor):
        fake_zip = utils.make_xpi({'manifest.json': ''})
        utils.Extractor.parse(fake_zip)
        assert not rdf_extractor.called
        assert manifest_json_extractor.called

    @mock.patch('olympia.files.utils.ManifestJSONExtractor')
    @mock.patch('olympia.files.utils.RDFExtractor')
    def test_prefers_manifest_to_install_rdf(self, rdf_extractor,
                                             manifest_json_extractor):
        fake_zip = utils.make_xpi({'install.rdf': '', 'manifest.json': ''})
        utils.Extractor.parse(fake_zip)
        assert not rdf_extractor.called
        assert manifest_json_extractor.called

    @mock.patch('olympia.files.utils.os.path.getsize')
    def test_static_theme_max_size(self, getsize_mock):
        getsize_mock.return_value = settings.MAX_STATICTHEME_SIZE
        manifest = utils.ManifestJSONExtractor(
            '/fake_path', '{"theme": {}}').parse()

        # Calling to check it doesn't raise.
        assert utils.check_xpi_info(manifest, xpi_file=mock.Mock())

        # Increase the size though and it should raise an error.
        getsize_mock.return_value = settings.MAX_STATICTHEME_SIZE + 1
        with pytest.raises(forms.ValidationError) as exc:
            utils.check_xpi_info(manifest, xpi_file=mock.Mock())

        assert (
            exc.value.message ==
            u'Maximum size for WebExtension themes is 7.0 MB.')

        # dpuble check only static themes are limited
        manifest = utils.ManifestJSONExtractor(
            '/fake_path', '{}').parse()
        assert utils.check_xpi_info(manifest, xpi_file=mock.Mock())


class TestRDFExtractor(TestCase):
    def setUp(self):
        self.firefox_versions = [
            AppVersion.objects.create(application=amo.APPS['firefox'].id,
                                      version='38.0a1'),
            AppVersion.objects.create(application=amo.APPS['firefox'].id,
                                      version='43.0'),
        ]
        self.thunderbird_versions = [
            AppVersion.objects.create(application=amo.APPS['android'].id,
                                      version='42.0'),
            AppVersion.objects.create(application=amo.APPS['android'].id,
                                      version='45.0'),
        ]

    def test_apps_disallow_thunderbird_and_seamonkey(self):
        zip_file = utils.SafeZip(get_addon_file(
            'valid_firefox_and_thunderbird_addon.xpi'))
        extracted = utils.RDFExtractor(zip_file).parse()
        apps = extracted['apps']
        assert len(apps) == 1
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '38.0a1'
        assert apps[0].max.version == '43.0'


class TestManifestJSONExtractor(AppVersionsMixin, TestCase):
    def parse(self, base_data):
        return utils.ManifestJSONExtractor(
            '/fake_path', json.dumps(base_data)).parse()

    def test_instanciate_without_data(self):
        """Without data, we load the data from the file path."""
        data = {'id': 'some-id'}
        fake_zip = utils.make_xpi({'manifest.json': json.dumps(data)})

        extractor = utils.ManifestJSONExtractor(zipfile.ZipFile(fake_zip))
        assert extractor.data == data

    def test_guid_from_applications(self):
        """Use applications>gecko>id for the guid."""
        assert self.parse(
            {'applications': {
                'gecko': {
                    'id': 'some-id'}}})['guid'] == 'some-id'

    def test_guid_from_browser_specific_settings(self):
        """Use applications>gecko>id for the guid."""
        assert self.parse(
            {'browser_specific_settings': {
                'gecko': {
                    'id': 'some-id'}}})['guid'] == 'some-id'

    def test_name_for_guid_if_no_id(self):
        """Don't use the name for the guid if there is no id."""
        assert self.parse({'name': 'addon-name'})['guid'] is None

    def test_type(self):
        """manifest.json addons are always ADDON_EXTENSION."""
        assert self.parse({})['type'] == amo.ADDON_EXTENSION

    def test_is_restart_required(self):
        """manifest.json addons never requires restart."""
        assert self.parse({})['is_restart_required'] is False

    def test_name(self):
        """Use name for the name."""
        assert self.parse({'name': 'addon-name'})['name'] == 'addon-name'

    def test_version(self):
        """Use version for the version."""
        assert self.parse({'version': '23.0.1'})['version'] == '23.0.1'

    def test_homepage(self):
        """Use homepage_url for the homepage."""
        assert (
            self.parse({'homepage_url': 'http://my-addon.org'})['homepage'] ==
            'http://my-addon.org')

    def test_summary(self):
        """Use description for the summary."""
        assert (
            self.parse({'description': 'An addon.'})['summary'] == 'An addon.')

    def test_invalid_strict_min_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': 'A',
                    'id': '@invalid_strict_min_version'
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert (
            exc.value.message ==
            'Lowest supported "strict_min_version" is 42.0.')

    def test_unknown_strict_min_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '76.0',
                    'id': '@unknown_strict_min_version'
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == (
            u'Unknown "strict_min_version" 76.0 for Firefox')

    def test_unknown_strict_max_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_max_version': '76.0',
                    'id': '@unknown_strict_min_version'
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_strict_min_version_needs_to_be_higher_then_42_if_specified(self):
        """strict_min_version needs to be higher than 42.0 if specified."""
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '36.0',
                    'id': '@too_old_strict_min_version'
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert (
            exc.value.message ==
            'Lowest supported "strict_min_version" is 42.0.')

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '47.0')
        firefox_max_version = self.create_appversion('firefox', '47.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=47.0',
                    'strict_max_version': '=47.*',
                    'id': '@random'
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

        # We have no way of specifying a different version for Android when an
        # explicit version number is provided... That being said, we know that
        # 47.0 is too low for Android, so we silently cap it at 48.0. That
        # forces us to also change the max version for android.
        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        # But if 'browser_specific_settings' is used, it's higher min version.
        data = {'browser_specific_settings': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == (
            amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == (
            amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_is_webextension(self):
        assert self.parse({})['is_webextension']

    def test_allow_static_theme_waffle(self):
        manifest = utils.ManifestJSONExtractor(
            '/fake_path', '{"theme": {}}').parse()

        utils.check_xpi_info(manifest)

        assert self.parse({'theme': {}})['type'] == amo.ADDON_STATICTHEME

    def test_extensions_dont_have_strict_compatibility(self):
        assert self.parse({})['strict_compatibility'] is False

    def test_moz_signed_extension_no_strict_compat(self):
        addon = amo.tests.addon_factory()
        user = amo.tests.user_factory(email='foo@mozilla.com')
        file_obj = addon.current_version.all_files[0]
        file_obj.update(is_mozilla_signed_extension=True)
        fixture = (
            'src/olympia/files/fixtures/files/'
            'legacy-addon-already-signed-0.1.0.xpi')

        with amo.tests.copy_file(fixture, file_obj.file_path):
            parsed = utils.parse_xpi(file_obj.file_path, user=user)
            assert parsed['is_mozilla_signed_extension']
            assert not parsed['strict_compatibility']

    def test_moz_signed_extension_reuse_strict_compat(self):
        addon = amo.tests.addon_factory()
        user = amo.tests.user_factory(email='foo@mozilla.com')
        file_obj = addon.current_version.all_files[0]
        file_obj.update(is_mozilla_signed_extension=True)
        fixture = (
            'src/olympia/files/fixtures/files/'
            'legacy-addon-already-signed-strict-compat-0.1.0.xpi')

        with amo.tests.copy_file(fixture, file_obj.file_path):
            parsed = utils.parse_xpi(file_obj.file_path, user=user)
            assert parsed['is_mozilla_signed_extension']

            # We set `strictCompatibility` in install.rdf
            assert parsed['strict_compatibility']

    @mock.patch('olympia.addons.models.resolve_i18n_message')
    def test_mozilla_trademark_disallowed(self, resolve_message):
        resolve_message.return_value = 'Notify Mozilla'

        addon = amo.tests.addon_factory()
        file_obj = addon.current_version.all_files[0]
        fixture = (
            'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi')

        with amo.tests.copy_file(fixture, file_obj.file_path):
            with pytest.raises(forms.ValidationError) as exc:
                utils.parse_xpi(file_obj.file_path)
                assert dict(exc.value.messages)['en-us'].startswith(
                    u'Add-on names cannot contain the Mozilla or'
                )

    @mock.patch('olympia.addons.models.resolve_i18n_message')
    @override_switch('content-optimization', active=False)
    def test_mozilla_trademark_for_prefix_allowed(self, resolve_message):
        resolve_message.return_value = 'Notify for Mozilla'

        addon = amo.tests.addon_factory()
        file_obj = addon.current_version.all_files[0]
        fixture = (
            'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi')

        with amo.tests.copy_file(fixture, file_obj.file_path):
            utils.parse_xpi(file_obj.file_path)

    def test_apps_use_default_versions_if_applications_is_omitted(self):
        """
        WebExtensions are allowed to omit `applications[/gecko]` and we
        previously skipped defaulting to any `AppVersion` once this is not
        defined. That resulted in none of our plattforms being selectable.

        See https://github.com/mozilla/addons-server/issues/2586 and
        probably many others.
        """
        data = {}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_handle_utf_bom(self):
        manifest = b'\xef\xbb\xbf{"manifest_version": 2, "name": "..."}'
        parsed = utils.ManifestJSONExtractor(None, manifest).parse()
        assert parsed['name'] == '...'

    def test_raise_error_if_no_optional_id_support(self):
        """
        We only support optional ids in Firefox 48+ and will throw an error
        otherwise.
        """
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '42.0',
                    'strict_max_version': '49.0',
                }
            }
        }

        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)['apps']

        assert (
            exc.value.message ==
            'Add-on ID is required for Firefox 47 and below.')

    def test_comments_are_allowed(self):
        json_string = """
        {
            // Required
            "manifest_version": 2,
            "name": "My Extension",
            "version": "versionString",

            // Recommended
            "default_locale": "en",
            "description": "A plain text description"
        }
        """
        manifest = utils.ManifestJSONExtractor(
            '/fake_path', json_string).parse()

        assert manifest['is_webextension'] is True
        assert manifest.get('name') == 'My Extension'

    def test_dont_skip_apps_because_of_strict_version_incompatibility(self):
        # We shouldn't skip adding specific apps to the WebExtension
        # no matter any potential incompatibility, e.g
        # browser_specific_settings is only supported from Firefox 48.0
        # onwards, now if the user specifies strict_min_compat as 42.0
        # we shouldn't skip the app because of that. Instead we override the
        # value with the known min version that started supporting that.
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_min_version': '42.0',
                    'id': '@random'
                }
            }
        }

        apps = self.parse(data)['apps']
        assert len(apps) == 2

        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (
            amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (
            amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)


class TestLanguagePackAndDictionaries(AppVersionsMixin, TestCase):
    def test_parse_langpack(self):
        self.create_appversion('firefox', '60.0')
        self.create_appversion('firefox', '60.*')
        self.create_appversion('android', '60.0')
        self.create_appversion('android', '60.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=60.0',
                    'strict_max_version': '=60.*',
                    'id': '@langp'
                }
            },
            'langpack_id': 'foo'
        }

        parsed_data = utils.ManifestJSONExtractor(
            '/fake_path', json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['strict_compatibility'] is True
        assert parsed_data['is_webextension'] is True

        apps = parsed_data['apps']
        assert len(apps) == 1  # Langpacks are not compatible with android.
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '60.0'
        assert apps[0].max.version == '60.*'

    def test_parse_langpack_not_targeting_versions_explicitly(self):
        data = {
            'applications': {
                'gecko': {
                    'id': '@langp'
                }
            },
            'langpack_id': 'foo'
        }

        parsed_data = utils.ManifestJSONExtractor(
            '/fake_path', json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['strict_compatibility'] is True
        assert parsed_data['is_webextension'] is True

        apps = parsed_data['apps']
        assert len(apps) == 1  # Langpacks are not compatible with android.
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '42.0'
        # The linter should force the langpack to have a strict_max_version,
        # so the value here doesn't matter much.
        assert apps[0].max.version == '*'

    def test_parse_dictionary(self):
        self.create_appversion('firefox', '61.0')
        data = {
            'applications': {
                'gecko': {
                    'id': '@dict'
                }
            },
            'dictionaries': {'en-US': '/path/to/en-US.dic'}
        }

        parsed_data = utils.ManifestJSONExtractor(
            '/fake_path', json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_DICT
        assert parsed_data['strict_compatibility'] is False
        assert parsed_data['is_webextension'] is True
        assert parsed_data['target_locale'] == 'en-US'

        apps = parsed_data['apps']
        assert len(apps) == 1  # Dictionaries are not compatible with android.
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '61.0'
        assert apps[0].max.version == '*'

    def test_parse_broken_dictionary(self):
        data = {
            'dictionaries': {}
        }
        with self.assertRaises(forms.ValidationError):
            utils.ManifestJSONExtractor('/fake_path', json.dumps(data)).parse()

    def test_check_xpi_info_langpack_submission_restrictions(self):
        user = user_factory()
        self.create_appversion('firefox', '60.0')
        self.create_appversion('firefox', '60.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=60.0',
                    'strict_max_version': '=60.*',
                    'id': '@langp'
                }
            },
            'langpack_id': 'foo'
        }
        parsed_data = utils.ManifestJSONExtractor(
            '/fake_path.xpi', json.dumps(data)).parse()

        with self.assertRaises(ValidationError):
            # Regular users aren't allowed to submit langpacks.
            utils.check_xpi_info(parsed_data, xpi_file=mock.Mock(), user=user)

        # Shouldn't raise for users with proper permissions
        self.grant_permission(user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        utils.check_xpi_info(parsed_data, xpi_file=mock.Mock(), user=user)


class TestManifestJSONExtractorStaticTheme(TestManifestJSONExtractor):
    def parse(self, base_data):
        if 'theme' not in base_data.keys():
            base_data.update(theme={})
        return super(
            TestManifestJSONExtractorStaticTheme, self).parse(base_data)

    def test_type(self):
        assert self.parse({})['type'] == amo.ADDON_STATICTHEME

    def test_apps_use_default_versions_if_applications_is_omitted(self):
        """
        Override this because static themes have a higher default version.
        """
        data = {}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '66.0')
        firefox_max_version = self.create_appversion('firefox', '66.*')
        android_min_version = self.create_appversion('android', '66.0')
        android_max_version = self.create_appversion('android', '66.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=66.0',
                    'strict_max_version': '=66.*',
                    'id': '@random'
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min == firefox_min_version
        assert apps[0].max == firefox_max_version
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min == android_min_version
        assert apps[1].max == android_max_version

    def test_theme_json_extracted(self):
        # Check theme data is extracted from the manifest and returned.
        data = {'theme': {'colors': {'tab_background_text': "#3deb60"}}}
        assert self.parse(data)['theme'] == data['theme']

    def test_unknown_strict_max_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_max_version': '76.0',
                    'id': '@unknown_strict_min_version'
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_dont_skip_apps_because_of_strict_version_incompatibility(self):
        # In the parent class this method would bump the min_version to 48.0
        # because that's the first version to support
        # browser_specific_settings, but in static themes we bump it even
        # higher because of the minimum version when we started supporting
        # static themes themselves.
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_min_version': '42.0',
                    'id': '@random'
                }
            }
        }

        apps = self.parse(data)['apps']
        assert len(apps) == 2

        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION


@pytest.mark.parametrize('filename, expected_files', [
    ('webextension_no_id.xpi', [
        'README.md', 'beasts', 'button', 'content_scripts', 'manifest.json',
        'popup'
    ]),
    ('webextension_no_id.zip', [
        'README.md', 'beasts', 'button', 'content_scripts', 'manifest.json',
        'popup'
    ]),
    ('webextension_no_id.tar.gz', [
        'README.md', 'beasts', 'button', 'content_scripts', 'manifest.json',
        'popup'
    ]),
    ('webextension_no_id.tar.bz2', [
        'README.md', 'beasts', 'button', 'content_scripts', 'manifest.json',
        'popup'
    ]),
    ('search.xml', [
        'search.xml',
    ])
])
def test_extract_extension_to_dest(filename, expected_files):
    extension_file = 'src/olympia/files/fixtures/files/{fname}'.format(
        fname=filename)

    with mock.patch('olympia.files.utils.os.fsync') as fsync_mock:
        temp_folder = utils.extract_extension_to_dest(extension_file)

    assert sorted(os.listdir(temp_folder)) == expected_files

    # fsync isn't called by default
    assert not fsync_mock.called


@pytest.mark.parametrize('filename', [
    'webextension_no_id.xpi', 'webextension_no_id.zip',
    'webextension_no_id.tar.bz2', 'webextension_no_id.tar.gz', 'search.xml',
])
def test_extract_extension_to_dest_call_fsync(filename):
    extension_file = 'src/olympia/files/fixtures/files/{fname}'.format(
        fname=filename)

    with mock.patch('olympia.files.utils.os.fsync') as fsync_mock:
        utils.extract_extension_to_dest(extension_file, force_fsync=True)

    # fsync isn't called by default
    assert fsync_mock.called


def test_extract_extension_to_dest_non_existing_archive():
    extension_file = 'src/olympia/files/fixtures/files/doesntexist.zip'

    with mock.patch('olympia.files.utils.shutil.rmtree') as mock_rmtree:
        with pytest.raises(FileNotFoundError):
            utils.extract_extension_to_dest(extension_file)

    # Make sure we are cleaning up our temporary directory if possible
    assert mock_rmtree.called


def test_extract_extension_to_dest_invalid_archive():
    extension_file = (
        'src/olympia/files/fixtures/files/invalid-cp437-encoding.xpi'
    )

    with mock.patch('olympia.files.utils.shutil.rmtree') as mock_rmtree:
        with pytest.raises(forms.ValidationError):
            utils.extract_extension_to_dest(extension_file)

    # Make sure we are cleaning up our temporary directory if possible
    assert mock_rmtree.called


@pytest.fixture
def file_obj():
    addon = amo.tests.addon_factory()
    addon.update(guid='xxxxx')
    version = addon.current_version
    return version.all_files[0]


@pytestmark
def test_bump_version_in_manifest_json(file_obj):
    AppVersion.objects.create(application=amo.FIREFOX.id,
                              version=amo.DEFAULT_WEBEXT_MIN_VERSION)
    AppVersion.objects.create(application=amo.FIREFOX.id,
                              version=amo.DEFAULT_WEBEXT_MAX_VERSION)
    AppVersion.objects.create(application=amo.ANDROID.id,
                              version=amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
    AppVersion.objects.create(application=amo.ANDROID.id,
                              version=amo.DEFAULT_WEBEXT_MAX_VERSION)
    with amo.tests.copy_file(
            'src/olympia/files/fixtures/files/webextension.xpi',
            file_obj.file_path):
        utils.update_version_number(file_obj, '0.0.1.1-signed')
        parsed = utils.parse_xpi(file_obj.file_path)
        assert parsed['version'] == '0.0.1.1-signed'


def test_extract_translations_simple(file_obj):
    extension = 'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi'
    with amo.tests.copy_file(extension, file_obj.file_path):
        messages = utils.extract_translations(file_obj)
        assert list(sorted(messages.keys())) == [
            'de', 'en-US', 'ja', 'nb-NO', 'nl', 'ru', 'sv-SE']


@mock.patch('olympia.files.utils.zipfile.ZipFile.read')
def test_extract_translations_fail_silent_invalid_file(read_mock, file_obj):
    extension = 'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi'

    with amo.tests.copy_file(extension, file_obj.file_path):
        read_mock.side_effect = KeyError

        # Does not raise an exception
        utils.extract_translations(file_obj)

        read_mock.side_effect = IOError

        # Does not raise an exception too
        utils.extract_translations(file_obj)

        # We don't fail on invalid JSON too, this is addons-linter domain
        read_mock.side_effect = ValueError

        utils.extract_translations(file_obj)

        # But everything else...
        read_mock.side_effect = TypeError

        with pytest.raises(TypeError):
            utils.extract_translations(file_obj)


def test_get_all_files():
    tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)

    os.mkdir(os.path.join(tempdir, 'dir1'))

    _touch(os.path.join(tempdir, 'foo1'))
    _touch(os.path.join(tempdir, 'dir1', 'foo2'))

    assert utils.get_all_files(tempdir) == [
        os.path.join(tempdir, 'dir1'),
        os.path.join(tempdir, 'dir1', 'foo2'),
        os.path.join(tempdir, 'foo1'),
    ]

    shutil.rmtree(tempdir)
    assert not os.path.exists(tempdir)


def test_get_all_files_strip_prefix_no_prefix_silent():
    tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)

    os.mkdir(os.path.join(tempdir, 'dir1'))

    _touch(os.path.join(tempdir, 'foo1'))
    _touch(os.path.join(tempdir, 'dir1', 'foo2'))

    # strip_prefix alone doesn't do anything.
    assert utils.get_all_files(tempdir, strip_prefix=tempdir) == [
        os.path.join(tempdir, 'dir1'),
        os.path.join(tempdir, 'dir1', 'foo2'),
        os.path.join(tempdir, 'foo1'),
    ]


def test_get_all_files_prefix():
    tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)

    os.mkdir(os.path.join(tempdir, 'dir1'))

    _touch(os.path.join(tempdir, 'foo1'))
    _touch(os.path.join(tempdir, 'dir1', 'foo2'))

    # strip_prefix alone doesn't do anything.
    assert utils.get_all_files(tempdir, prefix='/foo/bar') == [
        '/foo/bar' + os.path.join(tempdir, 'dir1'),
        '/foo/bar' + os.path.join(tempdir, 'dir1', 'foo2'),
        '/foo/bar' + os.path.join(tempdir, 'foo1'),
    ]


def test_get_all_files_prefix_with_strip_prefix():
    tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)

    os.mkdir(os.path.join(tempdir, 'dir1'))

    _touch(os.path.join(tempdir, 'foo1'))
    _touch(os.path.join(tempdir, 'dir1', 'foo2'))

    # strip_prefix alone doesn't do anything.
    result = utils.get_all_files(
        tempdir, strip_prefix=tempdir, prefix='/foo/bar')
    assert result == [
        os.path.join('/foo', 'bar', 'dir1'),
        os.path.join('/foo', 'bar', 'dir1', 'foo2'),
        os.path.join('/foo', 'bar', 'foo1'),
    ]


def test_lock_with_lock_attained():
    with utils.lock(settings.TMP_PATH, 'test-lock-lock2') as lock_attained:
        assert lock_attained


@contextlib.contextmanager
def _run_lock_holding_process(lock_name, sleep):
    def _other_process_holding_lock():
        with utils.lock(settings.TMP_PATH, lock_name) as lock_attained:
            assert lock_attained
            time.sleep(sleep)

    other_process = multiprocessing.Process(target=_other_process_holding_lock)
    other_process.start()

    # Give the process some time to acquire the lock
    time.sleep(0.2)

    yield other_process

    other_process.join()


def test_lock_timeout():
    with _run_lock_holding_process('test-lock-lock3', sleep=2):
        # Waiting for 3 seconds allows us to attain the lock from the parent
        # process.
        lock = utils.lock(settings.TMP_PATH, 'test-lock-lock3', timeout=3)
        with lock as lock_attained:
            assert lock_attained

    with _run_lock_holding_process('test-lock-lock3', sleep=2):
        # Waiting only 1 second fails to acquire the lock
        lock = utils.lock(settings.TMP_PATH, 'test-lock-lock3', timeout=1)
        with lock as lock_attained:
            assert not lock_attained


def test_parse_search_empty_shortname():
    from olympia.files.tests.test_file_viewer import get_file

    fname = get_file('search_empty_shortname.xml')

    with pytest.raises(forms.ValidationError) as excinfo:
        utils.parse_search(fname)

    assert (
        str(excinfo.value.message) ==
        'Could not parse uploaded file, missing or empty <ShortName> element')


class TestResolvei18nMessage(object):
    def test_no_match(self):
        assert utils.resolve_i18n_message('foo', {}, '') == 'foo'

    def test_locale_found(self):
        messages = {
            'de': {
                'foo': {'message': 'bar'}
            }
        }

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'de')
        assert result == 'bar'

    def test_uses_default_locale(self):
        messages = {
            'en-US': {
                'foo': {'message': 'bar'}
            }
        }

        result = utils.resolve_i18n_message(
            '__MSG_foo__', messages, 'de', 'en')
        assert result == 'bar'

    def test_no_locale_match(self):
        # Neither `locale` or `locale` are found, "message" is returned
        # unchanged
        messages = {
            'fr': {
                'foo': {'message': 'bar'}
            }
        }

        result = utils.resolve_i18n_message(
            '__MSG_foo__', messages, 'de', 'en')
        assert result == '__MSG_foo__'

    def test_field_not_set(self):
        """Make sure we don't fail on messages that are `None`

        Fixes https://github.com/mozilla/addons-server/issues/3067
        """
        result = utils.resolve_i18n_message(None, {}, 'de', 'en')
        assert result is None

    def test_field_no_string(self):
        """Make sure we don't fail on messages that are no strings"""
        result = utils.resolve_i18n_message([], {}, 'de', 'en')
        assert result == []

    def test_corrects_locales(self):
        messages = {
            'en-US': {
                'foo': {'message': 'bar'}
            }
        }

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en')
        assert result == 'bar'

    def test_ignore_wrong_format(self):
        messages = {
            'en-US': {
                'foo': 'bar'
            }
        }

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en')
        assert result == '__MSG_foo__'


class TestXMLVulnerabilities(TestCase):
    """Test a few known vulnerabilities to make sure
    our defusedxml patching is applied automatically.

    This doesn't replicate all defusedxml tests.
    """

    def test_quadratic_xml(self):
        quadratic_xml = os.path.join(
            os.path.dirname(__file__), '..', 'fixtures', 'files',
            'quadratic.xml')

        with pytest.raises(forms.ValidationError) as exc:
            utils.extract_search(quadratic_xml)

        assert exc.value.message == u'OpenSearch: XML Security error.'

    def test_general_entity_expansion_is_disabled(self):
        zip_file = utils.SafeZip(os.path.join(
            os.path.dirname(__file__), '..', 'fixtures', 'files',
            'xxe-example-install.zip'))

        # This asserts that the malicious install.rdf blows up with
        # a parse error. If it gets as far as this specific parse error
        # it means that the external entity was not processed.
        #

        # Before the patch in files/utils.py, this would raise an IOError
        # from the test suite refusing to make an external HTTP request to
        # the entity ref.
        with pytest.raises(EntitiesForbidden):
            utils.RDFExtractor(zip_file)

    def test_lxml_XMLParser_no_resolve_entities(self):
        with pytest.raises(NotSupportedError):
            lxml.etree.XMLParser(resolve_entities=True)

        # not setting it works
        lxml.etree.XMLParser()

        # Setting it explicitly to `False` is fine too.
        lxml.etree.XMLParser(resolve_entities=False)


class TestGetBackgroundImages(TestCase):
    file_obj = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
    file_obj_dep = os.path.join(
        settings.ROOT,
        'src/olympia/devhub/tests/addons/static_theme_deprecated.zip')

    def test_get_background_images(self):
        data = {'images': {'theme_frame': 'weta.png'}}

        images = utils.get_background_images(self.file_obj, data)
        assert 'weta.png' in images
        assert len(images.items()) == 1
        assert len(images['weta.png']) == 126447

    def test_get_background_deprecated(self):
        data = {'images': {'headerURL': 'weta.png'}}

        images = utils.get_background_images(self.file_obj_dep, data)
        assert 'weta.png' in images
        assert len(images.items()) == 1
        assert len(images['weta.png']) == 126447

    def test_get_background_images_no_theme_data_provided(self):
        images = utils.get_background_images(self.file_obj, theme_data=None)
        assert 'weta.png' in images
        assert len(images.items()) == 1
        assert len(images['weta.png']) == 126447

    def test_get_background_images_missing(self):
        data = {'images': {'theme_frame': 'missing_file.png'}}

        images = utils.get_background_images(self.file_obj, data)
        assert not images

    def test_get_background_images_not_image(self):
        self.file_obj = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/static_theme_non_image.zip')
        data = {'images': {'theme_frame': 'not_an_image.js'}}

        images = utils.get_background_images(self.file_obj, data)
        assert not images

    def test_get_background_images_with_additional_imgs(self):
        self.file_obj = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/static_theme_tiled.zip')
        data = {'images': {
            'theme_frame': 'empty.png',
            'additional_backgrounds': [
                'transparent.gif', 'missing_&_ignored.png',
                'weta_for_tiling.png']
        }}

        images = utils.get_background_images(self.file_obj, data)
        assert len(images.items()) == 3
        assert len(images['empty.png']) == 332
        assert len(images['transparent.gif']) == 42
        assert len(images['weta_for_tiling.png']) == 93371

        # And again but only with the header image
        images = utils.get_background_images(
            self.file_obj, data, header_only=True)
        assert len(images.items()) == 1
        assert len(images['empty.png']) == 332


@pytest.mark.parametrize('value, expected', [
    (1, '1/1/1'),
    (1, '1/1/1'),
    (12, '2/12/12'),
    (123, '3/23/123'),
    (123456789, '9/89/123456789'),
])
def test_id_to_path(value, expected):
    assert utils.id_to_path(value) == expected


class TestSafeZip(TestCase):
    def test_raises_error_for_invalid_webextension_xpi(self):
        with pytest.raises(forms.ValidationError):
            utils.SafeZip(get_addon_file('invalid_webextension.xpi'))

    def test_raises_validation_error_when_uncompressed_size_is_too_large(self):
        with override_settings(MAX_ZIP_UNCOMPRESSED_SIZE=1000):
            with pytest.raises(forms.ValidationError):
                # total uncompressed size of this xpi is: 2269 bytes
                utils.SafeZip(get_addon_file(
                    'valid_firefox_and_thunderbird_addon.xpi'))


class TestArchiveMemberValidator(TestCase):
    # We cannot easily test `archive_member_validator` so let's test
    # `_validate_archive_member_name_and_size` instead.

    def test_raises_when_filename_is_none(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size(None, 123)

    def test_raises_when_filesize_is_none(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size('filename', None)

    def test_raises_when_filename_is_dot_dot_slash(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size('../', 123)

    def test_raises_when_filename_starts_with_slash(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size('/..', 123)

    def test_raises_when_filename_is_dot_dot(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size('..', 123)

    def test_does_not_raise_when_filename_is_dot_dot_extension(self):
        utils._validate_archive_member_name_and_size('foo..svg', 123)

    @override_settings(FILE_UNZIP_SIZE_LIMIT=100)
    def test_raises_when_filesize_is_above_limit(self):
        with pytest.raises(forms.ValidationError):
            utils._validate_archive_member_name_and_size(
                'filename',
                settings.FILE_UNZIP_SIZE_LIMIT + 100
            )
