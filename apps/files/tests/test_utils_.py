import json
from tempfile import NamedTemporaryFile

import pytest
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from applications.models import AppVersion
from files.models import File
from files.utils import (find_jetpacks, is_beta, ManifestJSONExtractor,
                         PackageJSONExtractor)
from versions.models import Version


pytestmark = pytest.mark.django_db


def test_is_beta():
    assert not is_beta('1.2')

    assert is_beta('1.2a')
    assert is_beta('1.2a1')
    assert is_beta('1.2a123')
    assert is_beta('1.2a.1')
    assert is_beta('1.2a.123')
    assert is_beta('1.2a-1')
    assert is_beta('1.2a-123')

    assert is_beta('1.2alpha')
    assert is_beta('1.2alpha')
    assert is_beta('1.2alpha1')
    assert is_beta('1.2alpha123')
    assert is_beta('1.2alpha.1')
    assert is_beta('1.2alpha.123')
    assert is_beta('1.2alpha-1')
    assert is_beta('1.2alpha-123')

    assert is_beta('1.2b')
    assert is_beta('1.2b1')
    assert is_beta('1.2b123')
    assert is_beta('1.2b.1')
    assert is_beta('1.2b.123')
    assert is_beta('1.2b-1')
    assert is_beta('1.2b-123')

    assert is_beta('1.2beta')
    assert is_beta('1.2beta1')
    assert is_beta('1.2beta123')
    assert is_beta('1.2beta.1')
    assert is_beta('1.2beta.123')
    assert is_beta('1.2beta-1')
    assert is_beta('1.2beta-123')

    assert is_beta('1.2pre')
    assert is_beta('1.2pre1')
    assert is_beta('1.2pre123')
    assert is_beta('1.2pre.1')
    assert is_beta('1.2pre.123')
    assert is_beta('1.2pre-1')
    assert is_beta('1.2pre-123')

    assert is_beta('1.2rc')
    assert is_beta('1.2rc1')
    assert is_beta('1.2rc123')
    assert is_beta('1.2rc.1')
    assert is_beta('1.2rc.123')
    assert is_beta('1.2rc-1')
    assert is_beta('1.2rc-123')


class TestFindJetpacks(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestFindJetpacks, self).setUp()
        File.objects.update(jetpack_version='1.0')
        self.file = File.objects.filter(version__addon=3615).get()

    def test_success(self):
        files = find_jetpacks('1.0', '1.1')
        eq_(files, [self.file])

    def test_skip_autorepackage(self):
        Addon.objects.update(auto_repackage=False)
        eq_(find_jetpacks('1.0', '1.1'), [])

    def test_minver(self):
        files = find_jetpacks('1.1', '1.2')
        eq_(files, [self.file])
        eq_(files[0].needs_upgrade, False)

    def test_maxver(self):
        files = find_jetpacks('.1', '1.0')
        eq_(files, [self.file])
        eq_(files[0].needs_upgrade, False)

    def test_unreviewed_files_plus_reviewed_file(self):
        # We upgrade unreviewed files up to the latest reviewed file.
        v = Version.objects.create(addon_id=3615)
        new_file = File.objects.create(version=v, jetpack_version='1.0')
        Version.objects.create(addon_id=3615)
        new_file2 = File.objects.create(version=v, jetpack_version='1.0')
        eq_(new_file.status, amo.STATUS_UNREVIEWED)
        eq_(new_file2.status, amo.STATUS_UNREVIEWED)

        files = find_jetpacks('1.0', '1.1')
        eq_(files, [self.file, new_file, new_file2])
        assert all(f.needs_upgrade for f in files)

        # Now self.file will not need an upgrade since we skip old versions.
        new_file.update(status=amo.STATUS_PUBLIC)
        files = find_jetpacks('1.0', '1.1')
        eq_(files, [self.file, new_file, new_file2])
        eq_(files[0].needs_upgrade, False)
        assert all(f.needs_upgrade for f in files[1:])


class TestPackageJSONExtractor(amo.tests.TestCase):

    def parse(self, base_data):
        return PackageJSONExtractor('/fake_path',
                                    json.dumps(base_data)).parse()

    def create_appversion(self, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id,
                                         version=version)

    def test_instanciate_without_data(self):
        """Without data, we load the data from the file path."""
        data = {'id': 'some-id'}
        with NamedTemporaryFile() as file_:
            file_.write(json.dumps(data))
            file_.flush()
            mje = ManifestJSONExtractor(file_.name)
            assert mje.data == data

    def test_guid(self):
        """Use id for the guid."""
        assert self.parse({'id': 'some-id'})['guid'] == 'some-id'

    def test_name_for_guid_if_no_id(self):
        """Use the name for the guid if there is no id."""
        assert self.parse({'name': 'addon-name'})['guid'] == 'addon-name'

    def test_type(self):
        """Package.json addons are always ADDON_EXTENSION."""
        assert self.parse({})['type'] == amo.ADDON_EXTENSION

    def test_no_restart(self):
        """Package.json addons are always no-restart."""
        assert self.parse({})['no_restart'] is True

    def test_name_from_title_with_name(self):
        """Use the title for the name."""
        data = {'title': 'The Addon Title', 'name': 'the-addon-name'}
        assert self.parse(data)['name'] == 'The Addon Title'

    def test_name_from_name_without_title(self):
        """Use the name for the name if there is no title."""
        assert (
            self.parse({'name': 'the-addon-name'})['name'] == 'the-addon-name')

    def test_version(self):
        """Use version for the version."""
        assert self.parse({'version': '23.0.1'})['version'] == '23.0.1'

    def test_homepage(self):
        """Use homepage for the homepage."""
        assert (
            self.parse({'homepage': 'http://my-addon.org'})['homepage'] ==
            'http://my-addon.org')

    def test_summary(self):
        """Use description for the summary."""
        assert (
            self.parse({'description': 'An addon.'})['summary'] == 'An addon.')

    def test_apps(self):
        """Use engines for apps."""
        firefox_version = self.create_appversion('firefox', '33.0a1')
        thunderbird_version = self.create_appversion('thunderbird', '33.0a1')
        data = {'engines': {'firefox': '>=33.0a1', 'thunderbird': '>=33.0a1'}}
        apps = self.parse(data)['apps']
        apps_dict = dict((app.appdata.short, app) for app in apps)
        assert sorted(apps_dict.keys()) == ['firefox', 'thunderbird']
        assert apps_dict['firefox'].min == firefox_version
        assert apps_dict['firefox'].max == firefox_version
        assert apps_dict['thunderbird'].min == thunderbird_version
        assert apps_dict['thunderbird'].max == thunderbird_version

    def test_unknown_apps_are_ignored(self):
        """Unknown engines get ignored."""
        self.create_appversion('firefox', '33.0a1')
        self.create_appversion('thunderbird', '33.0a1')
        data = {
            'engines': {
                'firefox': '>=33.0a1',
                'thunderbird': '>=33.0a1',
                'node': '>=0.10',
            },
        }
        apps = self.parse(data)['apps']
        engines = [app.appdata.short for app in apps]
        assert sorted(engines) == ['firefox', 'thunderbird']  # Not node.

    def test_invalid_app_versions_are_ignored(self):
        """Valid engines with invalid versions are ignored."""
        firefox_version = self.create_appversion('firefox', '33.0a1')
        data = {
            'engines': {
                'firefox': '>=33.0a1',
                'fennec': '>=33.0a1',
            },
        }
        apps = self.parse(data)['apps']
        assert len(apps) == 1
        assert apps[0].appdata.short == 'firefox'
        assert apps[0].min == firefox_version
        assert apps[0].max == firefox_version

    def test_fennec_is_treated_as_android(self):
        """Treat the fennec engine as android."""
        android_version = self.create_appversion('android', '33.0a1')
        data = {
            'engines': {
                'fennec': '>=33.0a1',
                'node': '>=0.10',
            },
        }
        apps = self.parse(data)['apps']
        assert apps[0].appdata.short == 'android'
        assert apps[0].min == android_version
        assert apps[0].max == android_version


class TestManifestJSONExtractor(amo.tests.TestCase):

    def parse(self, base_data):
        return ManifestJSONExtractor('/fake_path',
                                     json.dumps(base_data)).parse()

    def create_appversion(self, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id,
                                         version=version)

    def test_instanciate_without_data(self):
        """Without data, we load the data from the file path."""
        data = {'id': 'some-id'}
        with NamedTemporaryFile() as file_:
            file_.write(json.dumps(data))
            file_.flush()
            mje = ManifestJSONExtractor(file_.name)
            assert mje.data == data

    def test_guid(self):
        """Use applications>gecko>id for the guid."""
        assert self.parse(
            {'applications': {
                'gecko': {
                    'id': 'some-id'}}})['guid'] == 'some-id'

    def test_name_for_guid_if_no_id(self):
        """Use the name for the guid if there is no id."""
        assert self.parse({'name': 'addon-name'})['guid'] == 'addon-name'

    def test_type(self):
        """manifest.json addons are always ADDON_EXTENSION."""
        assert self.parse({})['type'] == amo.ADDON_EXTENSION

    def test_no_restart(self):
        """manifest.json addons are always no-restart."""
        assert self.parse({})['no_restart'] is True

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

    def test_apps_use_provided_versions(self):
        """Use the min and max versions if provided."""
        firefox_min_version = self.create_appversion('firefox', '30.0')
        firefox_max_version = self.create_appversion('firefox', '30.*')
        self.create_appversion('firefox', '42.0')  # Default AppVersions.
        self.create_appversion('firefox', '42.*')
        data = {
            'applications': {
                'gecko': {
                    'strict_min_version': '>=30.0',
                    'strict_max_version': '=30.*'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1  # Only Firefox for now.
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

    def test_apps_use_default_versions_if_none_provided(self):
        """Use the default min and max versions if none provided."""
        # Default AppVersions.
        firefox_min_version = self.create_appversion('firefox', '42.0')
        firefox_max_version = self.create_appversion('firefox', '42.*')
        data = {'applications': {'gecko': {'id': 'some-id'}}}
        apps = self.parse(data)['apps']
        assert len(apps) == 1  # Only Firefox for now.
        app = apps[0]
        assert app.appdata == amo.FIREFOX
        assert app.min == firefox_min_version
        assert app.max == firefox_max_version

    def test_invalid_app_versions_are_ignored(self):
        """Invalid versions are ignored."""
        data = {
            'applications': {
                'gecko': {
                    # Not created, so are seen as invalid.
                    'strict_min_version': '>=30.0',
                    'strict_max_version': '=30.*'}}}
        assert not self.parse(data)['apps']
