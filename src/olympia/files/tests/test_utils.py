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
from django.core.files.storage import default_storage as storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.test.utils import override_settings

import pytest

from olympia import amo
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.tests.test_helpers import get_addon_file
from olympia.applications.models import AppVersion
from olympia.files import utils


pytestmark = pytest.mark.django_db


def _touch(fname):
    open(fname, 'a').close()
    os.utime(fname, None)


class AppVersionsMixin:
    @classmethod
    def setUpTestData(cls):
        cls.create_webext_default_versions()

    @classmethod
    def create_appversion(cls, name, version):
        return AppVersion.objects.get_or_create(
            application=amo.APPS[name].id, version=version
        )[0]

    @classmethod
    def create_webext_default_versions(cls):
        cls.create_appversion('firefox', '36.0')  # Incompatible with webexts.
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MAX_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MAX_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        cls.create_appversion('android', amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_ANDROID)


class TestManifestJSONExtractor(AppVersionsMixin, TestCase):
    def test_parse_xpi_no_manifest(self):
        fake_zip = utils.make_xpi({'dummy': 'dummy'})

        with mock.patch(
            'olympia.files.utils.get_file'
        ) as get_file_mock, self.assertRaises(utils.NoManifestFound) as exc:
            get_file_mock.return_value = fake_zip
            utils.parse_xpi(None)
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == ('No manifest.json found')

    def test_static_theme_max_size(self):
        xpi_file = mock.Mock(size=settings.MAX_STATICTHEME_SIZE - 1)
        manifest = utils.ManifestJSONExtractor('{"theme": {}}').parse()

        # Calling to check it doesn't raise.
        assert utils.check_xpi_info(manifest, xpi_file=xpi_file)

        # Increase the size though and it should raise an error.
        xpi_file.size = settings.MAX_STATICTHEME_SIZE + 1
        with pytest.raises(forms.ValidationError) as exc:
            utils.check_xpi_info(manifest, xpi_file=xpi_file)

        assert exc.value.message == 'Maximum size for WebExtension themes is 7.0 MB.'

        # dpuble check only static themes are limited
        manifest = utils.ManifestJSONExtractor('{}').parse()
        assert utils.check_xpi_info(manifest, xpi_file=xpi_file)

    def parse(self, base_data):
        return utils.ManifestJSONExtractor(json.dumps(base_data)).parse()

    def test_guid_from_applications(self):
        """Use applications>gecko>id for the guid."""
        assert (
            self.parse({'applications': {'gecko': {'id': 'some-id'}}})['guid']
            == 'some-id'
        )

    def test_guid_from_browser_specific_settings(self):
        """Use applications>gecko>id for the guid."""
        assert (
            self.parse({'browser_specific_settings': {'gecko': {'id': 'some-id'}}})[
                'guid'
            ]
            == 'some-id'
        )

    def test_non_string_guid(self):
        """Test that guid is converted to a string (or None)"""
        assert (
            self.parse({'browser_specific_settings': {'gecko': {'id': 12345}}})['guid']
            == '12345'
        )
        assert (
            self.parse({'browser_specific_settings': {'gecko': {'id': None}}})['guid']
            is None
        )

    def test_name_for_guid_if_no_id(self):
        """Don't use the name for the guid if there is no id."""
        assert self.parse({'name': 'addon-name'})['guid'] is None

    def test_type(self):
        """manifest.json addons with no specific properties present are extensions."""
        assert self.parse({})['type'] == amo.ADDON_EXTENSION

    def test_name(self):
        """Use name for the name."""
        assert self.parse({'name': 'addon-name'})['name'] == 'addon-name'

    def test_version(self):
        """Use version for the version."""
        assert self.parse({'version': '23.0.1'})['version'] == '23.0.1'

    def test_homepage(self):
        """Use homepage_url for the homepage."""
        expected_homepage = 'http://my-addon.org'
        assert (
            self.parse({'homepage_url': expected_homepage})['homepage']
            == expected_homepage
        )

    def test_homepage_with_developer_url(self):
        expected_homepage = 'http://my-addon.org'
        assert (
            self.parse(
                {
                    'homepage_url': 'http://should-be-overridden',
                    'developer': {'url': expected_homepage},
                }
            )['homepage']
            == expected_homepage
        )

    def test_homepage_with_developer_and_no_url(self):
        expected_homepage = 'http://my-addon.org'
        assert (
            self.parse(
                {
                    'homepage_url': expected_homepage,
                    'developer': {'name': 'some name'},
                }
            )['homepage']
            == expected_homepage
        )

    def test_summary(self):
        """Use description for the summary."""
        assert self.parse({'description': 'An addon.'})['summary'] == 'An addon.'

    def test_invalid_strict_min_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': 'A',
                    'id': '@invalid_strict_min_version',
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == 'Lowest supported "strict_min_version" is 42.0.'

    def test_unknown_strict_min_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '76.0',
                    'id': '@unknown_strict_min_version',
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == ('Unknown "strict_min_version" 76.0 for Firefox')

    def test_unknown_strict_max_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_max_version': '76.0',
                    'id': '@unknown_strict_max_version',
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == ('Unknown "strict_max_version" 76.0 for Firefox')

    def test_strict_min_version_needs_to_be_higher_than_42_if_specified(self):
        """strict_min_version needs to be higher than 42.0 if specified."""
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '36.0',
                    'id': '@too_old_strict_min_version',
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == 'Lowest supported "strict_min_version" is 42.0.'

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '47.0')
        firefox_max_version = self.create_appversion('firefox', '47.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=47.0',
                    'strict_max_version': '=47.*',
                    'id': '@random',
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

    def test_strict_min_version_100(self):
        firefox_min_version = self.create_appversion('firefox', '100.0')
        firefox_max_version = self.create_appversion('firefox', '100.*')
        android_min_version = self.create_appversion('android', '100.0')
        android_max_version = self.create_appversion('android', '100.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=100.0',
                    'strict_max_version': '=100.*',
                    'id': '@radioactive',
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
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        # And if mv3 then a higher min version again
        data['manifest_version'] = 3
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        app = apps[1]
        assert app.appdata == amo.ANDROID
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_ANDROID)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_static_theme(self):
        manifest = utils.ManifestJSONExtractor('{"theme": {}}').parse()
        utils.check_xpi_info(manifest)
        assert self.parse({'theme': {}})['type'] == amo.ADDON_STATICTHEME

    def test_extensions_dont_have_strict_compatibility(self):
        assert self.parse({})['strict_compatibility'] is False

    @mock.patch('olympia.addons.models.resolve_i18n_message')
    def test_mozilla_trademark_disallowed(self, resolve_message):
        resolve_message.return_value = 'Notify Mozilla'

        addon = amo.tests.addon_factory(
            file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
        )
        file_obj = addon.current_version.file
        with pytest.raises(forms.ValidationError) as exc:
            utils.parse_xpi(file_obj.file.path)
            assert dict(exc.value.messages)['en-us'].startswith(
                'Add-on names cannot contain the Mozilla or'
            )

    @mock.patch('olympia.addons.models.resolve_i18n_message')
    def test_mozilla_trademark_for_prefix_allowed(self, resolve_message):
        resolve_message.return_value = 'Notify for Mozilla'

        addon = amo.tests.addon_factory(
            file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
        )
        file_obj = addon.current_version.file

        utils.parse_xpi(file_obj.file.path)

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
        parsed = utils.ManifestJSONExtractor(manifest).parse()
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

        assert exc.value.message == 'Add-on ID is required for Firefox 47 and below.'

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
        manifest = utils.ManifestJSONExtractor(json_string).parse()

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
                'gecko': {'strict_min_version': '42.0', 'id': '@random'}
            }
        }

        apps = self.parse(data)['apps']
        assert len(apps) == 2

        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_BROWSER_SPECIFIC)

    def test_devtools_page(self):
        json_string = """
                {
                    // Required
                    "manifest_version": 2,
                    "name": "My Extension",
                    "version": "versionString",

                    // Recommended
                    "default_locale": "en",
                    "description": "A plain text description",

                    "devtools_page": "devtools/my-page.html"
                }
                """
        parsed_data = utils.ManifestJSONExtractor(json_string).parse()

        assert parsed_data['devtools_page'] == 'devtools/my-page.html'

    def test_version_not_string(self):
        """Test parsing doesn't fail if version is not a string - that error
        should be handled downstream by the linter."""
        data = {'version': 42}
        assert self.parse(data)['version'] == '42'

        data = {'version': 42.0}
        assert self.parse(data)['version'] == '42.0'

        # These are even worse, but what matters is that version stays a string
        # in the result.
        data = {'version': {}}
        assert self.parse(data)['version'] == '{}'

        data = {'version': []}
        assert self.parse(data)['version'] == '[]'

        data = {'version': None}
        assert self.parse(data)['version'] == 'None'

    def test_install_origins(self):
        self.parse({})['install_origins'] == []
        self.parse({'install_origins': ['https://fôo.com']})['install_origins'] == [
            'https://fôo.com'
        ]
        self.parse({'install_origins': ['https://bâr.net', 'https://alice.org']})[
            'install_origins'
        ] == ['https://bâr.net', 'https://alice.org']

    def test_install_origins_wrong_type_ignored(self):
        self.parse({'install_origins': 42})['install_origins'] == []
        self.parse({'install_origins': None})['install_origins'] == []
        self.parse({'install_origins': {}})['install_origins'] == []

    def test_install_origins_wrong_type_inside_list_ignored(self):
        self.parse({'install_origins': [42]})['install_origins'] == []
        self.parse({'install_origins': [None]})['install_origins'] == []
        self.parse({'install_origins': [{}]})['install_origins'] == []
        self.parse({'install_origins': [['https://inception.com']]})[
            'install_origins'
        ] == []
        self.parse({'install_origins': [42, 'https://goo.com']})['install_origins'] == [
            'https://goo.com'
        ]

        # 'flop' is not a valid origin, but the linter is responsible for that
        # validation. We just care about it being a string so that we don't
        # raise a TypeError later in the process.
        self.parse({'install_origins': [42, 'flop']})['install_origins'] == ['flop']


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
                    'id': '@langp',
                }
            },
            'langpack_id': 'foo',
        }

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['strict_compatibility'] is True

        apps = parsed_data['apps']
        assert len(apps) == 1  # Langpacks are not compatible with android.
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '60.0'
        assert apps[0].max.version == '60.*'

    def test_parse_langpack_not_targeting_versions_explicitly(self):
        data = {'applications': {'gecko': {'id': '@langp'}}, 'langpack_id': 'foo'}

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['strict_compatibility'] is True

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
            'applications': {'gecko': {'id': '@dict'}},
            'dictionaries': {'en-US': '/path/to/en-US.dic'},
        }

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_DICT
        assert parsed_data['strict_compatibility'] is False
        assert parsed_data['target_locale'] == 'en-US'

        apps = parsed_data['apps']
        assert len(apps) == 1  # Dictionaries are not compatible with android.
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == '61.0'
        assert apps[0].max.version == '*'

    def test_parse_broken_dictionary(self):
        data = {'dictionaries': {}}
        with self.assertRaises(forms.ValidationError):
            utils.ManifestJSONExtractor(json.dumps(data)).parse()

    def test_check_xpi_info_langpack_submission_restrictions(self):
        user = user_factory()
        self.create_appversion('firefox', '60.0')
        self.create_appversion('firefox', '60.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=60.0',
                    'strict_max_version': '=60.*',
                    'id': '@langp',
                }
            },
            'langpack_id': 'foo',
        }
        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()

        with self.assertRaises(ValidationError):
            # Regular users aren't allowed to submit langpacks.
            utils.check_xpi_info(parsed_data, xpi_file=mock.Mock(), user=user)

        # Shouldn't raise for users with proper permissions
        self.grant_permission(user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        utils.check_xpi_info(parsed_data, xpi_file=mock.Mock(), user=user)


class TestSitePermission(AppVersionsMixin, TestCase):
    def parse(self):
        return utils.ManifestJSONExtractor('{"site_permissions": ["webmidi"]}').parse()

    def test_allow_regular_submission_of_site_permissions_addons_with_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:SubmitSitePermission')
        parsed_data = self.parse()
        assert parsed_data['type'] == amo.ADDON_SITE_PERMISSION
        assert parsed_data['site_permissions'] == ['webmidi']
        assert utils.check_xpi_info(parsed_data, user=user)

    def test_allow_submission_of_site_permissions_addons_from_task_user(self):
        user = user_factory(pk=settings.TASK_USER_ID)
        parsed_data = self.parse()
        assert parsed_data['type'] == amo.ADDON_SITE_PERMISSION
        assert parsed_data['site_permissions'] == ['webmidi']
        assert utils.check_xpi_info(parsed_data, user=user)

    def test_disallow_regular_submission_of_site_permission_addons_no_user(self):
        parsed_data = self.parse()
        with self.assertRaises(ValidationError):
            utils.check_xpi_info(parsed_data)

    def test_disallow_regular_submission_of_site_permission_addons_normal_user(self):
        user = user_factory()
        parsed_data = self.parse()
        with self.assertRaises(ValidationError):
            utils.check_xpi_info(parsed_data, user=user)


class TestManifestJSONExtractorStaticTheme(TestManifestJSONExtractor):
    def parse(self, base_data):
        if 'theme' not in base_data.keys():
            base_data.update(theme={})
        return super().parse(base_data)

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
        assert apps[0].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
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
                    'id': '@random',
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
        data = {'theme': {'colors': {'tab_background_text': '#3deb60'}}}
        assert self.parse(data)['theme'] == data['theme']

    def test_unknown_strict_max_version(self):
        data = {
            'applications': {
                'gecko': {
                    'strict_max_version': '76.0',
                    'id': '@unknown_strict_max_version',
                }
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == ('Unknown "strict_max_version" 76.0 for Firefox')

    def test_dont_skip_apps_because_of_strict_version_incompatibility(self):
        # In the parent class this method would bump the min_version to 48.0
        # because that's the first version to support
        # browser_specific_settings, but in static themes we bump it even
        # higher because of the minimum version when we started supporting
        # static themes themselves.
        data = {
            'browser_specific_settings': {
                'gecko': {'strict_min_version': '42.0', 'id': '@random'}
            }
        }

        apps = self.parse(data)['apps']
        assert len(apps) == 2

        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID)
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION


@pytest.mark.parametrize(
    'filename, expected_files',
    [
        (
            'webextension_no_id.xpi',
            [
                'README.md',
                'beasts',
                'button',
                'content_scripts',
                'manifest.json',
                'popup',
            ],
        ),
        (
            'webextension_no_id.zip',
            [
                'README.md',
                'beasts',
                'button',
                'content_scripts',
                'manifest.json',
                'popup',
            ],
        ),
        (
            'webextension_no_id.tar.gz',
            [
                'README.md',
                'beasts',
                'button',
                'content_scripts',
                'manifest.json',
                'popup',
            ],
        ),
        (
            'webextension_no_id.tar.bz2',
            [
                'README.md',
                'beasts',
                'button',
                'content_scripts',
                'manifest.json',
                'popup',
            ],
        ),
    ],
)
def test_extract_extension_to_dest(filename, expected_files):
    extension_file = f'src/olympia/files/fixtures/files/{filename}'

    with mock.patch('olympia.files.utils.os.fsync') as fsync_mock:
        temp_folder = utils.extract_extension_to_dest(extension_file)

    assert sorted(os.listdir(temp_folder)) == expected_files

    # fsync isn't called by default
    assert not fsync_mock.called


@pytest.mark.parametrize(
    'filename',
    [
        'webextension_no_id.xpi',
        'webextension_no_id.zip',
        'webextension_no_id.tar.bz2',
        'webextension_no_id.tar.gz',
    ],
)
def test_extract_extension_to_dest_call_fsync(filename):
    extension_file = f'src/olympia/files/fixtures/files/{filename}'

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
    extension_file = 'src/olympia/files/fixtures/files/invalid-cp437-encoding.xpi'

    with mock.patch('olympia.files.utils.shutil.rmtree') as mock_rmtree:
        with pytest.raises(forms.ValidationError):
            utils.extract_extension_to_dest(extension_file)

    # Make sure we are cleaning up our temporary directory if possible
    assert mock_rmtree.called


@pytestmark
def test_bump_version_in_manifest_json():
    AppVersion.objects.create(
        application=amo.FIREFOX.id, version=amo.DEFAULT_WEBEXT_MIN_VERSION
    )
    AppVersion.objects.create(
        application=amo.FIREFOX.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
    )
    AppVersion.objects.create(
        application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
    )
    AppVersion.objects.create(
        application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
    )
    file_obj = amo.tests.addon_factory(
        file_kw={'filename': 'webextension.xpi'}
    ).current_version.file
    utils.update_version_number(file_obj, '0.0.1.1-signed')
    parsed = utils.parse_xpi(file_obj.file.path)
    assert parsed['version'] == '0.0.1.1-signed'


@pytestmark
def test_extract_translations_simple():
    file_obj = amo.tests.addon_factory(
        file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
    ).current_version.file
    messages = utils.extract_translations(file_obj)
    assert list(sorted(messages.keys())) == [
        'de',
        'en-US',
        'ja',
        'nb-NO',
        'nl',
        'ru',
        'sv-SE',
    ]


@pytestmark
@mock.patch('olympia.files.utils.zipfile.ZipFile.read')
def test_extract_translations_fail_silent_invalid_file(read_mock):
    file_obj = amo.tests.addon_factory(
        file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
    ).current_version.file

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
    result = utils.get_all_files(tempdir, strip_prefix=tempdir, prefix='/foo/bar')
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


class TestResolvei18nMessage:
    def test_no_match(self):
        assert utils.resolve_i18n_message('foo', {}, '') == 'foo'

    def test_locale_found(self):
        messages = {'de': {'foo': {'message': 'bar'}}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'de')
        assert result == 'bar'

    def test_uses_default_locale(self):
        messages = {'en-US': {'foo': {'message': 'bar'}}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'de', 'en')
        assert result == 'bar'

    def test_no_locale_match(self):
        # Neither `locale` or `locale` are found, "message" is returned
        # unchanged
        messages = {'fr': {'foo': {'message': 'bar'}}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'de', 'en')
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
        messages = {'en-US': {'foo': {'message': 'bar'}}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en')
        assert result == 'bar'

    def test_ignore_wrong_format(self):
        messages = {'en-US': {'foo': 'bar'}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en')
        assert result == '__MSG_foo__'


class TestGetBackgroundImages(TestCase):
    file_obj = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
    )
    file_obj_dep = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme_deprecated.zip'
    )

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

    @mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
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
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme_non_image.zip'
        )
        data = {'images': {'theme_frame': 'not_an_image.js'}}

        images = utils.get_background_images(self.file_obj, data)
        assert not images

    def test_get_background_images_with_additional_imgs(self):
        self.file_obj = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
        )
        data = {
            'images': {
                'theme_frame': 'empty.png',
                'additional_backgrounds': [
                    'transparent.gif',
                    'missing_&_ignored.png',
                    'weta_for_tiling.png',
                ],
            }
        }

        images = utils.get_background_images(self.file_obj, data)
        assert len(images.items()) == 3
        assert len(images['empty.png']) == 332
        assert len(images['transparent.gif']) == 42
        assert len(images['weta_for_tiling.png']) == 93371

        # And again but only with the header image
        images = utils.get_background_images(self.file_obj, data, header_only=True)
        assert len(images.items()) == 1
        assert len(images['empty.png']) == 332


@pytest.mark.parametrize(
    'value, expected',
    [
        (1, '1/01/1'),
        (12, '2/12/12'),
        (123, '3/23/123'),
        (1234, '4/34/1234'),
        (123456789, '9/89/123456789'),
    ],
)
def test_id_to_path(value, expected):
    assert utils.id_to_path(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        (1, '01/0001/1'),
        (12, '12/0012/12'),
        (123, '23/0123/123'),
        (1234, '34/1234/1234'),
        (123456, '56/3456/123456'),
        (123456789, '89/6789/123456789'),
    ],
)
def test_id_to_path_depth(value, expected):
    assert utils.id_to_path(value, breadth=2) == expected


class TestSafeZip(TestCase):
    def test_raises_error_for_invalid_webextension_xpi(self):
        with pytest.raises(zipfile.BadZipFile):
            utils.SafeZip(get_addon_file('invalid_webextension.xpi'))

    def test_raises_error_for_archive_with_backslashes_in_filenames(self):
        filename = (
            'src/olympia/files/'
            'fixtures/files/archive-with-invalid-chars-in-filenames.zip'
        )
        with pytest.raises(utils.InvalidZipFile):
            utils.SafeZip(filename)

    def test_ignores_error_for_archive_with_backslashes_in_filenames_with_argument(
        self,
    ):
        filename = (
            'src/olympia/files/'
            'fixtures/files/archive-with-invalid-chars-in-filenames.zip'
        )
        utils.SafeZip(filename, ignore_filename_errors=True)

    def test_raises_validation_error_when_uncompressed_size_is_too_large(self):
        with override_settings(MAX_ZIP_UNCOMPRESSED_SIZE=1000):
            with pytest.raises(utils.InvalidZipFile):
                # total uncompressed size of this xpi is 126kb
                utils.SafeZip(get_addon_file('mozilla_static_theme.zip'))


class TestArchiveMemberValidator(TestCase):
    # We cannot easily test `archive_member_validator` so let's test
    # `_validate_archive_member_name_and_size` instead.

    def test_raises_when_filename_is_none(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size(None, 123)

    def test_raises_when_filesize_is_none(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size('filename', None)

    def test_raises_when_filename_is_dot_dot_slash(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size('../', 123)

    def test_raises_when_filename_starts_with_slash(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size('/..', 123)

    def test_raises_when_filename_contains_backslashes(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size('path\\to\\file.txt', 123)

    def test_raises_when_filename_is_dot_dot(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size('..', 123)

    def test_ignores_when_filename_is_dot_dot_slash_with_argument(self):
        utils._validate_archive_member_name_and_size(
            '../', 123, ignore_filename_errors=True
        )

    def test_ignores_when_filename_starts_with_slash_with_argument(self):
        utils._validate_archive_member_name_and_size(
            '/..', 123, ignore_filename_errors=True
        )

    def test_ignores_when_filename_contains_backslashes_with_argument(self):
        utils._validate_archive_member_name_and_size(
            'path\\to\\file.txt', 123, ignore_filename_errors=True
        )

    def test_ignores_when_filename_is_dot_dot_with_argument(self):
        utils._validate_archive_member_name_and_size(
            '..', 123, ignore_filename_errors=True
        )

    def test_does_not_raise_when_filename_is_dot_dot_extension(self):
        utils._validate_archive_member_name_and_size('foo..svg', 123)

    @override_settings(FILE_UNZIP_SIZE_LIMIT=100)
    def test_raises_when_filesize_is_above_limit(self):
        with pytest.raises(utils.InvalidZipFile):
            utils._validate_archive_member_name_and_size(
                'filename', settings.FILE_UNZIP_SIZE_LIMIT + 100
            )


class TestWriteCrxAsXpi(TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.target = os.path.join(self.tempdir, 'target')
        self.prefix = 'src/olympia/files/fixtures/files'

    def tearDown(self):
        storage.delete(self.target)
        storage.delete(self.tempdir)

    # Note: those tests are also performed in test_models.py using
    # FileUpload.from_post() to ensure the relevant exception is caught if they
    # are raised and the add-on is then fully processed correctly. These just
    # test the underlying function that does the conversion from crx to xpi.

    def test_webextension_crx(self):
        path = os.path.join(self.prefix, 'webextension.crx')
        with open(path, 'rb') as source:
            utils.write_crx_as_xpi(source, self.target)
        assert zipfile.is_zipfile(self.target)

    def test_webextension_crx_large(self):
        path = os.path.join(self.prefix, 'https-everywhere.crx')
        with open(path, 'rb') as source:
            utils.write_crx_as_xpi(source, self.target)
        assert zipfile.is_zipfile(self.target)

    def test_webextension_crx_version_3(self):
        path = os.path.join(self.prefix, 'webextension_crx3.crx')
        with open(path, 'rb') as source:
            utils.write_crx_as_xpi(source, self.target)
        assert zipfile.is_zipfile(self.target)

    def test_webextension_crx_not_a_crx(self):
        file_ = SimpleUploadedFile(
            'foo.crx', b'Cr42\x02\x00\x00\x00&\x01\x00\x00\x00\x01\x00\x00'
        )
        with self.assertRaises(utils.InvalidOrUnsupportedCrx) as exc:
            utils.write_crx_as_xpi(file_, self.target)
        assert str(exc.exception) == 'CRX file does not start with Cr24'
        # It's the caller responsability to move the original file there, as if
        # it was a regular zip, since we couldn't convert it.
        assert not storage.exists(self.target)

    def test_webextension_crx_version_unsupported(self):
        file_ = SimpleUploadedFile(
            'foo.crx', b'Cr24\x04\x00\x00\x00&\x01\x00\x00\x00\x01\x00\x00'
        )
        with self.assertRaises(utils.InvalidOrUnsupportedCrx) as exc:
            utils.write_crx_as_xpi(file_, self.target)
        assert str(exc.exception) == 'Unsupported CRX version'
        # It's the caller responsability to move the original file there, as if
        # it was a regular zip, since we couldn't convert it.
        assert not storage.exists(self.target)

    def test_webextension_crx_version_cant_unpack(self):
        file_ = SimpleUploadedFile(
            'foo.crx', b'Cr24\x02\x00\x00\x00&\x00\x00\x00\x01\x00\x00'
        )
        with self.assertRaises(utils.InvalidOrUnsupportedCrx) as exc:
            utils.write_crx_as_xpi(file_, self.target)
        assert str(exc.exception) == 'Invalid or corrupt CRX file'
        # It's the caller responsability to move the original file there, as if
        # it was a regular zip, since we couldn't convert it.
        assert not storage.exists(self.target)
