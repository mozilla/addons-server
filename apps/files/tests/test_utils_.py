from nose.tools import eq_

import amo.tests
import files.utils
from addons.models import Addon
from files.models import File
from files.utils import find_jetpacks
from versions.models import Version


class TestFindJetpacks(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
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
        v2 = Version.objects.create(addon_id=3615)
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
