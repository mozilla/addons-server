import hashlib
import os
import tempfile

from django.conf import settings
from django.db import models

import mock
import test_utils
from nose.tools import eq_

import amo
from addons.models import Addon
from files import tasks


class TestRepackageJetpack(test_utils.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        urllib_patch = mock.patch('files.tasks.urllib')
        self.urllib = urllib_patch.start()
        self.addCleanup(urllib_patch.stop)

        self.addon = Addon.objects.get(id=3615)
        # Match the guid from jetpack.xpi.
        self.addon.update(guid='jid0-ODIKJS9b4IT3H1NYlPKr0NDtLuE@jetpack')
        self.file = self.addon.current_version.all_files[0]
        assert self.file.status == amo.STATUS_PUBLIC

        # Set up a temp file so urllib.urlretrieve works.
        self.xpi_path = os.path.join(settings.ROOT,
                                     'apps/files/fixtures/files/jetpack.xpi')
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        tmp_file.write(open(self.xpi_path, 'rb').read())
        tmp_file.flush()
        self.urllib.urlretrieve.return_value = (tmp_file.name, None)

    def builder_data(self, **kw):
        """Generate a builder_data dictionary with sensible defaults."""
        data = {'id': self.addon.id, 'result': 'success', 'msg': 'ok',
                'file_id': self.file.id, 'location': 'http://new.file'}
        data.update(kw)
        return data

    def test_result_not_success(self):
        data = self.builder_data(result='fail', msg='oops')
        eq_(tasks.repackage_jetpack(data), None)

    def test_bad_addon_id(self):
        data = self.builder_data(id=22)
        with self.assertRaises(models.ObjectDoesNotExist):
            tasks.repackage_jetpack(data)

    def test_bad_file_id(self):
        data = self.builder_data(file_id=234234)
        with self.assertRaises(models.ObjectDoesNotExist):
            tasks.repackage_jetpack(data)

    def test_urllib_failure(self):
        self.urllib.urlretrieve.side_effect = StopIteration
        with self.assertRaises(StopIteration):
            tasks.repackage_jetpack(self.builder_data())

    def test_new_file_hash(self):
        new_file = tasks.repackage_jetpack(self.builder_data())
        hash_ = hashlib.sha256()
        hash_.update(open(self.xpi_path, 'rb').read())
        eq_(new_file.hash, 'sha256:' + hash_.hexdigest())

    def test_new_version(self):
        num_versions = self.addon.versions.count()
        new_file = tasks.repackage_jetpack(self.builder_data())
        eq_(num_versions + 1, self.addon.versions.count())

        new_version = self.addon.versions.latest()
        new_version.all_files = [new_file]

    def test_new_version_number(self):
        tasks.repackage_jetpack(self.builder_data())
        new_version = self.addon.versions.latest()
        # From jetpack.xpi.
        eq_(new_version.version, '1.3')

    def test_new_file_status(self):
        new_file = tasks.repackage_jetpack(self.builder_data())
        eq_(new_file.status, self.file.status)

    def test_addon_current_version(self):
        new_file = tasks.repackage_jetpack(self.builder_data())
        addon = Addon.objects.get(id=self.addon.id)
        eq_(addon.current_version, new_file.version)
