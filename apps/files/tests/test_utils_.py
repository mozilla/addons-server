import json
from contextlib import contextmanager
from tempfile import NamedTemporaryFile

import pytest
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from applications.models import AppVersion
from files.models import File
from files.utils import find_jetpacks, is_beta, PackageJSONExtractor
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

    def test_ignore_non_builder_jetpacks(self):
        File.objects.update(builder_version=None)
        files = find_jetpacks('.1', '1.0', from_builder_only=True)
        eq_(files, [])

    def test_find_builder_jetpacks_only(self):
        File.objects.update(builder_version='2.0.1')
        files = find_jetpacks('.1', '1.0', from_builder_only=True)
        eq_(files, [self.file])


class TestPackageJSONExtractor(amo.tests.TestCase):

    @contextmanager
    def extractor(self, base_data):
        with NamedTemporaryFile() as f:
            f.write(json.dumps(base_data))
            f.flush()
            yield PackageJSONExtractor(f.name)

    def create_appversion(self, name, version):
        return AppVersion.objects.create(application=amo.APPS[name].id,
                                         version=version)

    def test_guid(self):
        """Use id for the guid."""
        with self.extractor({'id': 'some-id'}) as extractor:
            eq_(extractor.parse()['guid'], 'some-id')

    def test_name_for_guid_if_no_id(self):
        """Use the name for the guid if there is no id."""
        with self.extractor({'name': 'addon-name'}) as extractor:
            eq_(extractor.parse()['guid'], 'addon-name')

    def test_type(self):
        """Package.json addons are always ADDON_EXTENSION."""
        with self.extractor({}) as extractor:
            eq_(extractor.parse()['type'], amo.ADDON_EXTENSION)

    def test_no_restart(self):
        """Package.json addons are always no-restart."""
        with self.extractor({}) as extractor:
            eq_(extractor.parse()['no_restart'], True)

    def test_name_from_title_with_name(self):
        """Use the title for the name."""
        data = {'title': 'The Addon Title', 'name': 'the-addon-name'}
        with self.extractor(data) as extractor:
            eq_(extractor.parse()['name'], 'The Addon Title')

    def test_name_from_name_without_title(self):
        """Use the name for the name if there is no title."""
        with self.extractor({'name': 'the-addon-name'}) as extractor:
            eq_(extractor.parse()['name'], 'the-addon-name')

    def test_version(self):
        """Use version for the version."""
        with self.extractor({'version': '23.0.1'}) as extractor:
            eq_(extractor.parse()['version'], '23.0.1')

    def test_homepage(self):
        """Use homepage for the homepage."""
        with self.extractor({'homepage': 'http://my-addon.org'}) as extractor:
            eq_(extractor.parse()['homepage'], 'http://my-addon.org')

    def test_summary(self):
        """Use description for the summary."""
        with self.extractor({'description': 'An addon.'}) as extractor:
            eq_(extractor.parse()['summary'], 'An addon.')

    def test_apps(self):
        """Use engines for apps."""
        firefox_version = self.create_appversion('firefox', '33.0a1')
        thunderbird_version = self.create_appversion('thunderbird', '33.0a1')
        data = {
            'engines': {
                'firefox': '>=33.0a1',
                'thunderbird': '>=33.0a1',
            },
        }
        with self.extractor(data) as extractor:
            apps = extractor.parse()['apps']
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
        with self.extractor(data) as extractor:
            apps = extractor.parse()['apps']
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
        with self.extractor(data) as extractor:
            apps = extractor.parse()['apps']
            eq_(len(apps), 1)
            eq_(apps[0].appdata.short, 'firefox')
            eq_(apps[0].min, firefox_version)
            eq_(apps[0].max, firefox_version)

    def test_fennec_is_treated_as_android(self):
        """Treat the fennec engine as android."""
        android_version = self.create_appversion('android', '33.0a1')
        data = {
            'engines': {
                'fennec': '>=33.0a1',
                'node': '>=0.10',
            },
        }
        with self.extractor(data) as extractor:
            apps = extractor.parse()['apps']
            eq_(apps[0].appdata.short, 'android')
            eq_(apps[0].min, android_version)
            eq_(apps[0].max, android_version)
