import json
import os
import shutil
import tempfile
import time
import zipfile

from datetime import timedelta

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage

import flufl.lock
import lxml
import mock
import pytest

from defusedxml.common import EntitiesForbidden, NotSupportedError

from olympia import amo
from olympia.amo.tests import TestCase, create_switch
from olympia.applications.models import AppVersion
from olympia.files import utils
from olympia.files.tests.test_helpers import get_file


pytestmark = pytest.mark.django_db


def _touch(fname):
    open(fname, 'a').close()
    os.utime(fname, None)


def test_is_beta():
    assert not utils.is_beta('1.2')

    assert utils.is_beta('1.2a')
    assert utils.is_beta('1.2a1')
    assert utils.is_beta('1.2a123')
    assert utils.is_beta('1.2a.1')
    assert utils.is_beta('1.2a.123')
    assert utils.is_beta('1.2a-1')
    assert utils.is_beta('1.2a-123')

    assert utils.is_beta('1.2alpha')
    assert utils.is_beta('1.2alpha')
    assert utils.is_beta('1.2alpha1')
    assert utils.is_beta('1.2alpha123')
    assert utils.is_beta('1.2alpha.1')
    assert utils.is_beta('1.2alpha.123')
    assert utils.is_beta('1.2alpha-1')
    assert utils.is_beta('1.2alpha-123')

    assert utils.is_beta('1.2b')
    assert utils.is_beta('1.2b1')
    assert utils.is_beta('1.2b123')
    assert utils.is_beta('1.2b.1')
    assert utils.is_beta('1.2b.123')
    assert utils.is_beta('1.2b-1')
    assert utils.is_beta('1.2b-123')

    assert utils.is_beta('1.2beta')
    assert utils.is_beta('1.2beta1')
    assert utils.is_beta('1.2beta123')
    assert utils.is_beta('1.2beta.1')
    assert utils.is_beta('1.2beta.123')
    assert utils.is_beta('1.2beta-1')
    assert utils.is_beta('1.2beta-123')

    assert utils.is_beta('1.2pre')
    assert utils.is_beta('1.2pre1')
    assert utils.is_beta('1.2pre123')
    assert utils.is_beta('1.2pre.1')
    assert utils.is_beta('1.2pre.123')
    assert utils.is_beta('1.2pre-1')
    assert utils.is_beta('1.2pre-123')

    assert utils.is_beta('1.2rc')
    assert utils.is_beta('1.2rc1')
    assert utils.is_beta('1.2rc123')
    assert utils.is_beta('1.2rc.1')
    assert utils.is_beta('1.2rc.123')
    assert utils.is_beta('1.2rc-1')
    assert utils.is_beta('1.2rc-123')


class TestExtractor(TestCase):

    def test_no_manifest(self):
        fake_zip = utils.make_xpi({'dummy': 'dummy'})

        with self.assertRaises(forms.ValidationError) as exc:
            utils.Extractor.parse(fake_zip)
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


class TestManifestJSONExtractor(TestCase):

    def parse(self, base_data):
        return utils.ManifestJSONExtractor(
            '/fake_path', json.dumps(base_data)).parse()

    def create_appversion(self, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id,
                                         version=version)

    def create_webext_default_versions(self):
        self.create_appversion('firefox', '36.0')  # Incompatible with webexts.
        self.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION)
        self.create_appversion('firefox', amo.DEFAULT_WEBEXT_MAX_VERSION)
        self.create_appversion('firefox', amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID)

    def test_instanciate_without_data(self):
        """Without data, we load the data from the file path."""
        data = {'id': 'some-id'}
        fake_zip = utils.make_xpi({'manifest.json': json.dumps(data)})

        extractor = utils.ManifestJSONExtractor(zipfile.ZipFile(fake_zip))
        assert extractor.data == data

    def test_guid(self):
        """Use applications>gecko>id for the guid."""
        assert self.parse(
            {'applications': {
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

        self.create_webext_default_versions()
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
        assert len(apps) == 1
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        self.create_webext_default_versions()

        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1  # Only Firefox for now.
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_is_webextension(self):
        assert self.parse({})['is_webextension']

    def test_disallow_static_theme(self):
        manifest = utils.ManifestJSONExtractor(
            '/fake_path', '{"theme": {}}').parse()

        with pytest.raises(forms.ValidationError) as exc:
            utils.check_xpi_info(manifest)

        assert (
            exc.value.message ==
            'WebExtension theme uploads are currently not supported.')

    def test_allow_static_theme_waffle(self):
        create_switch('allow-static-theme-uploads')

        manifest = utils.ManifestJSONExtractor(
            '/fake_path', '{"theme": {}}').parse()

        utils.check_xpi_info(manifest)

        assert self.parse({'theme': {}})['type'] == amo.ADDON_STATICTHEME

    def test_is_e10s_compatible(self):
        data = self.parse({})
        assert data['e10s_compatibility'] == amo.E10S_COMPATIBLE_WEBEXTENSION

    def test_langpack(self):
        data = self.parse({'langpack_id': 'foo'})
        assert data['type'] == amo.ADDON_LPAPP
        assert data['strict_compatibility'] is True

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
        self.create_webext_default_versions()

        data = {}
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        # We support Android by default too
        self.create_appversion(
            'android', amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        self.create_appversion('android', amo.DEFAULT_WEBEXT_MAX_VERSION)

        apps = self.parse(data)['apps']

        assert apps[0].appdata == amo.FIREFOX
        assert apps[1].appdata == amo.ANDROID
        assert apps[1].min.version == amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
        assert apps[1].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_handle_utf_bom(self):
        manifest = '\xef\xbb\xbf{"manifest_version": 2, "name": "..."}'
        parsed = utils.ManifestJSONExtractor(None, manifest).parse()
        assert parsed['name'] == '...'

    def test_raise_error_if_no_optional_id_support(self):
        """
        We only support optional ids in Firefox 48+ and will throw an error
        otherwise.
        """
        self.create_webext_default_versions()

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
            'GUID is required for Firefox 47 and below.')

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

    def test_apps_contains_wrong_versions(self):
        """Use the min and max versions if provided."""
        self.create_webext_default_versions()
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '47.0.0',
                    'id': '@random'
                }
            }
        }

        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)['apps']

        assert exc.value.message.startswith('Cannot find min/max version.')


class TestManifestJSONExtractorStaticTheme(TestManifestJSONExtractor):
    def parse(self, base_data):
        if 'theme' not in base_data.keys():
            base_data.update(theme={})
        return super(
            TestManifestJSONExtractorStaticTheme, self).parse(base_data)

    def test_type(self):
        assert self.parse({})['type'] == amo.ADDON_STATICTHEME

    def create_webext_default_versions(self):
        self.create_appversion('firefox',
                               amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        return (super(TestManifestJSONExtractorStaticTheme, self)
                .create_webext_default_versions())

    def test_apps_use_default_versions_if_applications_is_omitted(self):
        """
        Override this because static themes have a higher default version.
        """
        self.create_webext_default_versions()

        data = {}
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        assert apps[0].appdata == amo.FIREFOX
        assert apps[0].min.version == (
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        assert apps[0].max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

        # Static themes don't support Android yet.  So check they aren't there.
        self.create_appversion(
            'android', amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID)
        self.create_appversion(
            'android', amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX)
        self.create_appversion('android', amo.DEFAULT_WEBEXT_MAX_VERSION)

        assert apps == self.parse(data)['apps']  # Same as before.

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        self.create_webext_default_versions()

        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1  # Only Firefox for now.
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min.version == amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX
        assert app.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '54.0')
        firefox_max_version = self.create_appversion('firefox', '54.*')

        self.create_webext_default_versions()
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=54.0',
                    'strict_max_version': '=54.*',
                    'id': '@random'
                }
            }
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

    def test_apps_contains_wrong_versions(self):
        """Use the min and max versions if provided."""
        self.create_webext_default_versions()
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '54.0.0',
                    'id': '@random'
                }
            }
        }

        with pytest.raises(forms.ValidationError) as exc:
            self.parse(data)['apps']

        assert exc.value.message.startswith('Cannot find min/max version.')

    def test_theme_json_extracted(self):
        # Check theme data is extracted from the manifest and returned.
        data = {'theme': {'colors': {'textcolor': "#3deb60"}}}
        assert self.parse(data)['theme'] == data['theme']


def test_zip_folder_content():
    extension_file = 'src/olympia/files/fixtures/files/extension.xpi'
    temp_filename, temp_folder = None, None
    try:
        temp_folder = utils.extract_zip(extension_file)
        assert sorted(os.listdir(temp_folder)) == [
            'chrome', 'chrome.manifest', 'install.rdf']
        temp_filename = amo.tests.get_temp_filename()
        utils.zip_folder_content(temp_folder, temp_filename)
        # Make sure the zipped files contain the same files.
        with zipfile.ZipFile(temp_filename, mode='r') as new:
            with zipfile.ZipFile(extension_file, mode='r') as orig:
                assert sorted(new.namelist()) == sorted(orig.namelist())
    finally:
        if temp_folder is not None and os.path.exists(temp_folder):
            amo.utils.rm_local_tmp_dir(temp_folder)
        if temp_filename is not None and os.path.exists(temp_filename):
            os.unlink(temp_filename)


def test_repack():
    # Warning: context managers all the way down. Because they're awesome.
    extension_file = 'src/olympia/files/fixtures/files/extension.xpi'
    # We don't want to overwrite our fixture, so use a copy.
    with amo.tests.copy_file_to_temp(extension_file) as temp_filename:
        # This is where we're really testing the repack helper.
        with utils.repack(temp_filename) as folder_path:
            # Temporary folder contains the unzipped XPI.
            assert sorted(os.listdir(folder_path)) == [
                'chrome', 'chrome.manifest', 'install.rdf']
            # Add a file, which should end up in the repacked file.
            with open(os.path.join(folder_path, 'foo.bar'), 'w') as file_:
                file_.write('foobar')
        # Once we're done with the repack, the temporary folder is removed.
        assert not os.path.exists(folder_path)
        # And the repacked file has the added file.
        assert os.path.exists(temp_filename)
        with zipfile.ZipFile(temp_filename, mode='r') as zf:
            assert 'foo.bar' in zf.namelist()
            assert zf.read('foo.bar') == 'foobar'


@pytest.fixture
def file_obj():
    addon = amo.tests.addon_factory()
    addon.update(guid='xxxxx')
    version = addon.current_version
    return version.all_files[0]


def test_bump_version_in_install_rdf(file_obj):
    with amo.tests.copy_file('src/olympia/files/fixtures/files/jetpack.xpi',
                             file_obj.file_path):
        utils.update_version_number(file_obj, '1.3.1-signed')
        parsed = utils.parse_xpi(file_obj.file_path)
        assert parsed['version'] == '1.3.1-signed'


def test_bump_version_in_alt_install_rdf(file_obj):
    with amo.tests.copy_file('src/olympia/files/fixtures/files/alt-rdf.xpi',
                             file_obj.file_path):
        utils.update_version_number(file_obj, '2.1.106.1-signed')
        parsed = utils.parse_xpi(file_obj.file_path)
        assert parsed['version'] == '2.1.106.1-signed'


def test_bump_version_in_package_json(file_obj):
    with amo.tests.copy_file(
            'src/olympia/files/fixtures/files/new-format-0.0.1.xpi',
            file_obj.file_path):
        utils.update_version_number(file_obj, '0.0.1.1-signed')

        with zipfile.ZipFile(file_obj.file_path, 'r') as source:
            parsed = json.loads(source.read('package.json'))
            assert parsed['version'] == '0.0.1.1-signed'


def test_bump_version_in_manifest_json(file_obj):
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


def test_atomic_lock_with():
    lock = flufl.lock.Lock('/tmp/test-atomic-lock1.lock')

    assert not lock.is_locked

    lock.lock()

    assert lock.is_locked

    with utils.atomic_lock('/tmp/', 'test-atomic-lock1') as lock_attained:
        assert not lock_attained

    lock.unlock()

    with utils.atomic_lock('/tmp/', 'test-atomic-lock1') as lock_attained:
        assert lock_attained


def test_atomic_lock_with_lock_attained():
    with utils.atomic_lock('/tmp/', 'test-atomic-lock2') as lock_attained:
        assert lock_attained


@mock.patch.object(flufl.lock._lockfile, 'CLOCK_SLOP', timedelta(seconds=0))
def test_atomic_lock_lifetime():
    def _get_lock():
        return utils.atomic_lock('/tmp/', 'test-atomic-lock3', lifetime=1)

    with _get_lock() as lock_attained:
        assert lock_attained

        lock2 = flufl.lock.Lock('/tmp/test-atomic-lock3.lock')

        with pytest.raises(flufl.lock.TimeOutError):
            # We have to apply `timedelta` to actually raise an exception,
            # otherwise `.lock()` will wait for 2 seconds and get the lock
            # for us. We get a `TimeOutError` because we were locking
            # with a different claim file
            lock2.lock(timeout=timedelta(seconds=0))

        with _get_lock() as lock_attained2:
            assert not lock_attained2

        time.sleep(2)

        with _get_lock() as lock_attained2:
            assert lock_attained2


def test_parse_search_empty_shortname():
    fname = get_file('search_empty_shortname.xml')

    with pytest.raises(forms.ValidationError) as excinfo:
        utils.parse_search(fname)

    assert (
        excinfo.value[0] ==
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

        with pytest.raises(EntitiesForbidden):
            utils.extract_search(quadratic_xml)

    def test_general_entity_expansion_is_disabled(self):
        zip_file = utils.SafeZip(os.path.join(
            os.path.dirname(__file__), '..', 'fixtures', 'files',
            'xxe-example-install.zip'))
        zip_file.is_valid()

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


def test_extract_header_img():
    file_obj = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
    data = {'images': {'headerURL': 'weta.png'}}
    dest_path = tempfile.mkdtemp()
    header_file = dest_path + '/weta.png'
    assert not default_storage.exists(header_file)

    utils.extract_header_img(file_obj, data, dest_path)
    assert default_storage.exists(header_file)
    assert default_storage.size(header_file) == 126447


def test_extract_header_img_missing():
    file_obj = os.path.join(
        settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
    data = {'images': {'headerURL': 'missing_file.png'}}
    dest_path = tempfile.mkdtemp()
    header_file = dest_path + '/missing_file.png'
    assert not default_storage.exists(header_file)

    utils.extract_header_img(file_obj, data, dest_path)
    assert not default_storage.exists(header_file)


def test_extract_header_with_additional_imgs():
    file_obj = os.path.join(
        settings.ROOT,
        'src/olympia/devhub/tests/addons/static_theme_tiled.zip')
    data = {'images': {
        'headerURL': 'empty.png',
        'additional_backgrounds': [
            'transparent.gif', 'missing_&_ignored.png', 'weta_for_tiling.png']
    }}
    dest_path = tempfile.mkdtemp()
    header_file = dest_path + '/empty.png'
    additional_file_1 = dest_path + '/transparent.gif'
    additional_file_2 = dest_path + '/weta_for_tiling.png'
    assert not default_storage.exists(header_file)
    assert not default_storage.exists(additional_file_1)
    assert not default_storage.exists(additional_file_2)

    utils.extract_header_img(file_obj, data, dest_path)
    assert default_storage.exists(header_file)
    assert default_storage.size(header_file) == 332
    assert default_storage.exists(additional_file_1)
    assert default_storage.size(additional_file_1) == 42
    assert default_storage.exists(additional_file_2)
    assert default_storage.size(additional_file_2) == 93371
