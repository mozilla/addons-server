import contextlib
import json
import multiprocessing
import os
import shutil
import tarfile
import tempfile
import time
import zipfile
from unittest import mock

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.test.utils import override_settings

import pytest

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory
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
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MAX_VERSION)
        cls.create_appversion('firefox', amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_ANDROID)
        cls.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID)
        cls.create_appversion('android', amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID)
        # Some additional test versions:
        cls.HIGHER_THAN_EVERYTHING_ELSE = '114.0'
        cls.HIGHER_THAN_EVERYTHING_ELSE_STAR = '114.*'
        cls.create_appversion('firefox', cls.HIGHER_THAN_EVERYTHING_ELSE)
        cls.create_appversion('android', cls.HIGHER_THAN_EVERYTHING_ELSE)
        cls.create_appversion('firefox', cls.HIGHER_THAN_EVERYTHING_ELSE_STAR)
        cls.create_appversion('android', cls.HIGHER_THAN_EVERYTHING_ELSE_STAR)


class TestManifestJSONExtractor(AppVersionsMixin, TestCase):
    def test_valid_json(self):
        assert self.parse({})

    def test_not_dict(self):
        with self.assertRaises(utils.InvalidManifest) as exc:
            utils.ManifestJSONExtractor('"foo@bar.com"').parse()
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == 'Could not parse the manifest file.'

    def test_fields_that_should_be_dicts(self):
        with self.assertRaises(utils.InvalidManifest) as exc:
            self.parse({'browser_specific_settings': []})
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == 'Could not parse the manifest file.'

        with self.assertRaises(utils.InvalidManifest) as exc:
            self.parse({'browser_specific_settings': {'gecko': 'lmao'}})
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == 'Could not parse the manifest file.'

        with self.assertRaises(utils.InvalidManifest) as exc:
            self.parse({'developer': 'rotfl'})
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == 'Could not parse the manifest file.'

        with self.assertRaises(utils.InvalidManifest) as exc:
            self.parse(
                {
                    'browser_specific_settings': {
                        'gecko': {'data_collection_permissions': []}
                    }
                }
            )
        assert isinstance(exc.exception, forms.ValidationError)
        assert exc.exception.message == 'Could not parse the manifest file.'

    def test_parse_xpi_no_manifest(self):
        fake_zip = utils.make_xpi({'dummy': 'dummy'})

        with (
            mock.patch('olympia.files.utils.get_file') as get_file_mock,
            self.assertRaises(utils.NoManifestFound) as exc,
        ):
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
        min_version = amo.DEFAULT_WEBEXT_MIN_VERSION
        assert (
            exc.value.message
            == f'Lowest supported "strict_min_version" is {min_version}.'
        )

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

    def test_strict_min_version_needs_to_be_higher_than_min_version_if_specified(self):
        """
        strict_min_version needs to be higher than amo.DEFAULT_WEBEXT_MIN_VERSION
        if specified.
        """
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '36.0',
                    'id': '@too_old_strict_min_version',
                }
            }
        }
        min_version = amo.DEFAULT_WEBEXT_MIN_VERSION
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert (
            exc.value.message
            == f'Lowest supported "strict_min_version" is {min_version}.'
        )

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '60.0')
        firefox_max_version = self.create_appversion('firefox', '60.*')
        android_min_version = self.create_appversion('android', '60.0')
        android_max_version = self.create_appversion('android', '60.*')

        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=60.0',
                    'strict_max_version': '=60.*',
                    'id': '@random',
                }
            }
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min == android_min_version
        assert app.max == android_max_version

        # Compatible, but not because of something in the manifest.
        # (gecko_android key is absent).
        assert not parsed_data['explicitly_compatible_with_android']

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
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min == firefox_min_version
        assert apps[0].max == firefox_max_version
        assert apps[1].application == amo.ANDROID.id
        assert apps[1].min == android_min_version
        assert apps[1].max == android_max_version

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # But if 'browser_specific_settings' is used, it's higher min version.
        data = {'browser_specific_settings': {'gecko': {'id': 'some-id'}}}
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # And if mv3 then a higher min version again
        data['manifest_version'] = 3
        apps = self.parse(data)['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == (amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_ANDROID)
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # Compatible, but not because of something in the manifest
        # (gecko_android key is absent).
        assert not parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_default_min_max(self):
        data = {'browser_specific_settings': {'gecko_android': {}}}
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # gecko_android is present but empty so we consider it's explicitly
        # compatible.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert (
            # Gray area: gecko_android is specified so we consider the origin
            # of the appversions is the manifest, even though technically there
            # were no values specified. The important point is that the
            # developer opted-in by using that key, so compatibility is locked.
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_default_min_if_only_max_is_present(self):
        data = {
            'browser_specific_settings': {'gecko_android': {'strict_max_version': '*'}}
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # gecko_android is present, that bumps the default min version for
        # android.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert (
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_strict_min_max(self):
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                }
            }
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # gecko_android is present with both min and max versions.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == self.HIGHER_THAN_EVERYTHING_ELSE
        assert app.max.version == self.HIGHER_THAN_EVERYTHING_ELSE_STAR
        assert (
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_strict_min_max_with_gecko_alongside(self):
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_min_version': amo.DEFAULT_WEBEXT_MIN_VERSION,
                },
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                },
            }
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST

        # gecko_android is present with both min and max versions.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == self.HIGHER_THAN_EVERYTHING_ELSE
        assert app.max.version == self.HIGHER_THAN_EVERYTHING_ELSE_STAR
        assert (
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_strict_min_default_max_with_gecko_alongside(self):
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                },
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                },
            }
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == self.HIGHER_THAN_EVERYTHING_ELSE_STAR
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST

        # we fall back on gecko's strict_max_version since it was specified.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == self.HIGHER_THAN_EVERYTHING_ELSE
        assert app.max.version == self.HIGHER_THAN_EVERYTHING_ELSE_STAR
        assert (
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_min_too_low(self):
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': '48.0',
                },
            }
        }
        parsed_data = self.parse(data)
        apps = parsed_data['apps']
        assert len(apps) == 2
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert app.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

        # strict min version is too low for gecko_android, we override it.
        app = apps[1]
        assert app.application == amo.ANDROID.id
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert (
            app.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

        assert parsed_data['explicitly_compatible_with_android']

    def test_gecko_android_unknown_min(self):
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': '142.0',
                },
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == (
            'Unknown "strict_min_version" 142.0 for Firefox for Android'
        )

    def test_gecko_android_unknown_max(self):
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_max_version': '142.0',
                },
            }
        }
        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)
        assert exc.value.message == (
            'Unknown "strict_max_version" 142.0 for Firefox for Android'
        )

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
    def test_bypass_name_checks(self, resolve_message):
        resolve_message.return_value = 'Notify Mozilla'

        addon = amo.tests.addon_factory(
            file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
        )
        file_obj = addon.current_version.file

        assert utils.parse_xpi(file_obj.file.path, bypass_name_checks=True)
        assert utils.parse_addon(
            file_obj.file.path, user=user_factory(), bypass_name_checks=True
        )

    @mock.patch('olympia.addons.models.resolve_i18n_message')
    def test_mozilla_trademark_for_prefix_allowed(self, resolve_message):
        resolve_message.return_value = 'Notify for Mozilla'

        addon = amo.tests.addon_factory(
            file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
        )
        file_obj = addon.current_version.file

        assert utils.parse_xpi(file_obj.file.path)

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
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        assert apps[1].application == amo.ANDROID.id
        assert apps[1].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_handle_utf_bom(self):
        manifest = b'\xef\xbb\xbf{"manifest_version": 2, "name": "..."}'
        parsed = utils.ManifestJSONExtractor(manifest).parse()
        assert parsed['name'] == '...'

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
        data = {'version': 58}
        assert self.parse(data)['version'] == '58'

        data = {'version': 58.0}
        assert self.parse(data)['version'] == amo.DEFAULT_WEBEXT_MIN_VERSION

        # These are even worse, but what matters is that version stays a string
        # in the result.
        data = {'version': {}}
        assert self.parse(data)['version'] == '{}'

        data = {'version': []}
        assert self.parse(data)['version'] == '[]'

        data = {'version': None}
        assert self.parse(data)['version'] == 'None'

    def test_install_origins(self):
        assert self.parse({})['install_origins'] == []
        assert self.parse({'install_origins': ['https://fôo.com']})[
            'install_origins'
        ] == ['https://fôo.com']
        assert self.parse(
            {'install_origins': ['https://bâr.net', 'https://alice.org']}
        )['install_origins'] == ['https://bâr.net', 'https://alice.org']

    def test_install_origins_wrong_type_ignored(self):
        assert self.parse({'install_origins': 42})['install_origins'] == []
        assert self.parse({'install_origins': None})['install_origins'] == []
        assert self.parse({'install_origins': {}})['install_origins'] == []

    def test_install_origins_wrong_type_inside_list_ignored(self):
        assert self.parse({'install_origins': [42]})['install_origins'] == []
        assert self.parse({'install_origins': [None]})['install_origins'] == []
        assert self.parse({'install_origins': [{}]})['install_origins'] == []
        assert (
            self.parse({'install_origins': [['https://inception.com']]})[
                'install_origins'
            ]
            == []
        )
        assert self.parse({'install_origins': [42, 'https://goo.com']})[
            'install_origins'
        ] == ['https://goo.com']

        # 'flop' is not a valid origin, but the linter is responsible for that
        # validation. We just care about it being a string so that we don't
        # raise a TypeError later in the process.
        assert self.parse({'install_origins': [42, 'flop']})['install_origins'] == [
            'flop'
        ]


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
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min.version == '60.0'
        assert apps[0].max.version == '60.*'

    def test_parse_langpack_not_targeting_versions_explicitly(self):
        data = {'applications': {'gecko': {'id': '@langp'}}, 'langpack_id': 'foo'}

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['strict_compatibility'] is True
        assert parsed_data['target_locale'] == 'foo'

        apps = parsed_data['apps']
        assert len(apps) == 1  # Langpacks are not compatible with android.
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
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
        assert apps[0].application == amo.FIREFOX.id
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

    def test_cant_change_locale_for_dictionary(self):
        self.create_appversion('firefox', '61.0')
        data = {
            'applications': {'gecko': {'id': '@dict'}},
            'dictionaries': {'en-US': '/path/to/en-US.dic'},
        }

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_DICT
        assert parsed_data['target_locale'] == 'en-US'
        assert utils.check_xpi_info(parsed_data)

        addon = addon_factory(type=amo.ADDON_DICT, target_locale='fr', guid='@dict')
        with self.assertRaises(ValidationError) as exc:
            utils.check_xpi_info(parsed_data, addon=addon)
        assert exc.exception.messages == [
            'The locale of an existing dictionary/language pack cannot be changed'
        ]

        addon.update(target_locale='en-US')
        assert utils.check_xpi_info(parsed_data, addon=addon)

    def test_cant_change_locale_for_langpack(self):
        user = user_factory()
        self.grant_permission(user, ':'.join(amo.permissions.LANGPACK_SUBMIT))
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
            'langpack_id': 'en-US',
        }

        parsed_data = utils.ManifestJSONExtractor(json.dumps(data)).parse()
        assert parsed_data['type'] == amo.ADDON_LPAPP
        assert parsed_data['target_locale'] == 'en-US'
        assert utils.check_xpi_info(parsed_data, user=user)

        addon = addon_factory(type=amo.ADDON_LPAPP, target_locale='fr', guid='@langp')
        with self.assertRaises(ValidationError) as exc:
            utils.check_xpi_info(parsed_data, addon=addon, user=user)
        assert exc.exception.messages == [
            'The locale of an existing dictionary/language pack cannot be changed'
        ]

        addon.update(target_locale='en-US')
        assert utils.check_xpi_info(parsed_data, addon=addon, user=user)


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
        assert len(apps) == 1
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min.version == (amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert apps[0].originated_from == amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '66.0')
        firefox_max_version = self.create_appversion('firefox', '66.*')

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
        assert len(apps) == 1
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min == firefox_min_version
        assert apps[0].max == firefox_max_version
        assert apps[0].originated_from == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST

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

    def test_strict_min_version_100(self):
        # Overridden because static themes are not compatible with Android.
        firefox_min_version = self.create_appversion('firefox', '100.0')
        firefox_max_version = self.create_appversion('firefox', '100.*')

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
        assert len(apps) == 1
        assert apps[0].application == amo.FIREFOX.id
        assert apps[0].min == firefox_min_version
        assert apps[0].max == firefox_max_version

    def test_gecko_android_default_min_max(self):
        # Overridden because static themes are not compatible with Android.
        data = {'browser_specific_settings': {'gecko_android': {}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_default_min_if_only_max_is_present(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {'gecko_android': {'strict_max_version': '*'}}
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_strict_min_max(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_strict_min_max_with_gecko_alongside(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_min_version': amo.DEFAULT_WEBEXT_MIN_VERSION,
                },
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                },
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_strict_min_default_max_with_gecko_alongside(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko': {
                    'strict_max_version': self.HIGHER_THAN_EVERYTHING_ELSE_STAR,
                },
                'gecko_android': {
                    'strict_min_version': self.HIGHER_THAN_EVERYTHING_ELSE,
                },
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == self.HIGHER_THAN_EVERYTHING_ELSE_STAR

    def test_gecko_android_min_too_low(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
                },
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_unknown_max(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_max_version': '142.0',
                },
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_gecko_android_unknown_min(self):
        # Overridden because static themes are not compatible with Android.
        data = {
            'browser_specific_settings': {
                'gecko_android': {
                    'strict_min_version': '142.0',
                },
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.application == amo.FIREFOX.id
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION


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
def test_extract_translations_fail_silent_invalid_file():
    file_obj = amo.tests.addon_factory(
        file_kw={'filename': 'notify-link-clicks-i18n.xpi'}
    ).current_version.file

    with mock.patch('olympia.files.utils.zipfile.ZipFile.read') as read_mock:
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

    def test_ignore_wrong_format_default(self):
        messages = {'en-US': {'foo': 'bar'}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en', 'fr')
        assert result == '__MSG_foo__'

    def test_ignore_wrong_format_no_default(self):
        messages = {'en-US': {'foo': 'bar'}}

        result = utils.resolve_i18n_message('__MSG_foo__', messages, 'en')
        assert result is None

    def test_resolve_placeholders_in_message(self):
        """Test that placeholders in the message string are correctly replaced."""
        app_desc_message = {
            'message': '$test_placeholder$ is replaced!',
            'placeholders': {'test_placeholder': {'content': 'Test Placeholder'}},
        }
        messages = {'en-US': {'app_desc': app_desc_message}}

        result = utils.resolve_i18n_message('__MSG_app_desc__', messages, 'en')
        assert result == 'Test Placeholder is replaced!'

    def test_app_without_content(self):
        """Test message with a placeholder but no content."""
        app_without_content_message = {
            'message': 'This $placeholder$ should not be replaced.',
            'placeholders': {'placeholder': {}},
        }
        messages = {'en-US': {'app_without_content': app_without_content_message}}

        result = utils.resolve_i18n_message(
            '__MSG_app_without_content__', messages, 'en-US'
        )
        assert result == 'This $placeholder$ should not be replaced.'

    def test_app_without_placeholder(self):
        """Test message without any placeholders."""
        app_without_placeholder_message = {
            'message': 'This message has no placeholders.',
        }
        messages = {
            'en-US': {'app_without_placeholder': app_without_placeholder_message}
        }

        result = utils.resolve_i18n_message(
            '__MSG_app_without_placeholder__', messages, 'en-US'
        )
        assert result == 'This message has no placeholders.'

    def test_app_with_invalid_placeholder(self):
        """Test message with invalid placeholder format."""
        app_with_invalid_placeholder_message = {
            'message': 'This $placeholder$ might cause issues.',
            'placeholders': 'Invalid format',
        }
        messages = {
            'en-US': {
                'app_with_invalid_placeholder': app_with_invalid_placeholder_message
            }
        }

        result = utils.resolve_i18n_message(
            '__MSG_app_with_invalid_placeholder__', messages, 'en-US'
        )
        assert result == 'This $placeholder$ might cause issues.'


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


class TestSafeZip(TestCase):
    def test_raises_error_for_invalid_webextension_xpi(self):
        with pytest.raises(zipfile.BadZipFile):
            utils.SafeZip(get_addon_file('invalid_webextension.xpi'))

    def test_raises_error_for_archive_with_backslashes_in_filenames(self):
        filename = (
            'src/olympia/files/'
            'fixtures/files/archive-with-invalid-chars-in-filenames.zip'
        )
        with pytest.raises(utils.InvalidArchiveFile):
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
            with pytest.raises(utils.InvalidArchiveFile):
                # total uncompressed size of this xpi is 126kb
                utils.SafeZip(get_addon_file('mozilla_static_theme.zip'))


class TestSafeTar(TestCase):
    def test_opens_regular_file(self):
        filename = './src/olympia/files/fixtures/files/webextension_no_id.tar.bz2'
        with utils.SafeTar.open(filename) as archive:
            assert archive.getmembers()

        filename = './src/olympia/files/fixtures/files/webextension_no_id.tar.gz'
        with utils.SafeTar.open(filename) as archive:
            assert archive.getmembers()

    def test_raises_error_symlink(self):
        filename = './src/olympia/files/fixtures/files/symlink.tar.gz'
        with self.assertRaises(utils.InvalidArchiveFile):
            utils.SafeTar.open(filename)

    def test_raises_error_for_absolute_path(self):
        filename = './src/olympia/files/fixtures/files/absolute.tar.gz'
        with self.assertRaises(utils.InvalidArchiveFile):
            utils.SafeTar.open(filename)


class TestArchiveMemberValidatorZip(TestCase):
    def _fake_archive_member(self, filename, filesize):
        info = zipfile.ZipInfo(filename)
        info.file_size = filesize
        return info

    def test_raises_when_filename_is_none(self):
        info = self._fake_archive_member('', 123)
        info.filename = None
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(info)

    def test_unsupported_compression_method(self):
        info = self._fake_archive_member('foo', 123)
        info.compress_type = zipfile.ZIP_DEFLATED
        # ZIP_DEFLATED works.
        utils.archive_member_validator(info)
        # ZIP_STORED works.
        info.compress_type = zipfile.ZIP_STORED
        utils.archive_member_validator(info)

        # The rest should raise an error. Test a few known ones out there:
        ZIP_DEFLATED64 = 9
        ZIP_IMPLODED = 10
        ZIP_BZIP2 = 12
        ZIP_LZMA = 14
        ZIP_ZSTANDARD = 93
        ZIP_XZ = 95
        ZIP_PPMD = 98
        for compress_type in (
            ZIP_DEFLATED64,
            ZIP_IMPLODED,
            ZIP_BZIP2,
            ZIP_LZMA,
            ZIP_ZSTANDARD,
            ZIP_XZ,
            ZIP_PPMD,
        ):
            info.compress_type = compress_type
            with pytest.raises(utils.InvalidArchiveFile):
                utils.archive_member_validator(info)

    def test_raises_when_filesize_is_none(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(self._fake_archive_member('filename', None))

    def test_raises_when_filename_is_dot_dot_slash(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(self._fake_archive_member('../', 123))

    def test_raises_when_filename_starts_with_slash(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(self._fake_archive_member('/..', 123))

    def test_raises_when_filename_contains_backslashes(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(
                self._fake_archive_member('path\\to\\file.txt', 123)
            )

    def test_raises_when_filename_is_dot_dot(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(self._fake_archive_member('..', 123))

    def test_ignores_when_filename_is_dot_dot_slash_with_argument(self):
        utils.archive_member_validator(
            self._fake_archive_member('../', 123), ignore_filename_errors=True
        )

    def test_ignores_when_filename_starts_with_slash_with_argument(self):
        utils.archive_member_validator(
            self._fake_archive_member('/..', 123), ignore_filename_errors=True
        )

    def test_ignores_when_filename_contains_backslashes_with_argument(self):
        utils.archive_member_validator(
            self._fake_archive_member('path\\to\\file.txt', 123),
            ignore_filename_errors=True,
        )

    def test_ignores_when_filename_is_dot_dot_with_argument(self):
        utils.archive_member_validator(
            self._fake_archive_member('..', 123), ignore_filename_errors=True
        )

    def test_does_not_raise_when_filename_is_dot_dot_extension(self):
        utils.archive_member_validator(self._fake_archive_member('foo..svg', 123))

    @override_settings(FILE_UNZIP_SIZE_LIMIT=100)
    def test_raises_when_filesize_is_above_limit(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(
                self._fake_archive_member(
                    'filename', settings.FILE_UNZIP_SIZE_LIMIT + 100
                )
            )


class TestArchiveMemberValidatorTar(TestArchiveMemberValidatorZip):
    def _fake_archive_member(self, filename, filesize):
        info = tarfile.TarInfo(filename)
        info.size = filesize
        return info

    def test_raises_when_filename_is_none(self):
        with pytest.raises(utils.InvalidArchiveFile):
            utils.archive_member_validator(self._fake_archive_member(None, 123))

    def test_unsupported_compression_method(self):
        info = self._fake_archive_member('foo', 123)
        # tar files members don't have a compress_type, we should not fail and
        # let it validate properly.
        assert not hasattr(info, 'compress_type')
        utils.archive_member_validator(info)


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
