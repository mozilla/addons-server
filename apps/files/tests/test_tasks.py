import hashlib
import os
import shutil
import tempfile
import urllib
import urlparse
import uuid

from django.conf import settings
from django.core import mail
from django.db import models

import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from addons.models import Addon
from applications.models import AppVersion
from files import tasks
from files.models import File
from files.utils import JetpackUpgrader


class TestUpgradeJetpacks(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestUpgradeJetpacks, self).setUp()

        urllib2_patch = mock.patch('files.tasks.urllib2')
        self.urllib2 = urllib2_patch.start()
        self.addCleanup(urllib2_patch.stop)
        JetpackUpgrader().jetpack_versions('0.9', '1.0')

    def test_send_request(self):
        addon = Addon.objects.get(id=3615)
        File.objects.all().update(jetpack_version='0.9')
        file_ = addon.current_version.all_files[0]
        tasks.start_upgrade([file_.id], sdk_version='1.2')
        assert self.urllib2.urlopen.called
        url, args = self.urllib2.urlopen.call_args[0]
        args = dict(urlparse.parse_qsl(args))
        self.assertDictEqual(args, {
            'addon': str(3615),
            'file_id': str(file_.id),
            'priority': 'low',
            'secret': settings.BUILDER_SECRET_KEY,
            'location': file_.get_url_path('builder'),
            'uuid': args['uuid'],  # uuid is random so steal from args.
            'pingback': absolutify(reverse('amo.builder-pingback')),
            'sdk_version': '1.2',
        })
        eq_(url, settings.BUILDER_UPGRADE_URL)


class TestRepackageJetpack(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestRepackageJetpack, self).setUp()

        urllib_patch = mock.patch('files.tasks.urllib')
        self.urllib = urllib_patch.start()
        self.addCleanup(urllib_patch.stop)

        self.addon = Addon.objects.get(id=3615)
        # Match the guid from jetpack.xpi.
        self.addon.update(guid='jid0-ODIKJS9b4IT3H1NYlPKr0NDtLuE@jetpack')
        self.file = self.addon.current_version.all_files[0]
        eq_(self.file.status, amo.STATUS_PUBLIC)

        # Set up a temp file so urllib.urlretrieve works.
        self.xpi_path = os.path.join(settings.ROOT,
                                     'apps/files/fixtures/files/jetpack.xpi')
        tmp_file = self.create_temp_file()
        self.urllib.urlretrieve.return_value = (tmp_file.name, None)

        self.upgrader = JetpackUpgrader()
        settings.SEND_REAL_EMAIL = True

        self.uuid = uuid.uuid4().hex

    def create_temp_file(self):
        tmp_file = tempfile.NamedTemporaryFile(delete=False,
                                               dir=settings.TMP_PATH)
        tmp_file.write(open(self.xpi_path, 'rb').read())
        tmp_file.flush()
        return tmp_file

    def builder_data(self, **kw):
        """Generate builder_data response dictionary with sensible defaults."""
        # Tell Redis we're sending to builder.
        self.upgrader.file(self.file.id, {'uuid': self.uuid,
                                          'file': self.file.id,
                                          'owner': 'bulk',
                                          'version': '1.0b4'})
        request = {'uuid': self.uuid, 'addon': self.addon.id,
                   'file_id': self.file.id}
        request.update((k, v) for k, v in kw.items() if k in request)
        data = {'result': 'success',
                'msg': 'ok',
                'location': 'http://new.file',
                # This fakes what we would send to the builder.
                'request': urllib.urlencode(request)}
        data.update(kw)
        return data

    def test_result_not_success(self):
        data = self.builder_data(result='fail', msg='oops')
        eq_(tasks.repackage_jetpack(data), None)

    def test_bad_addon_id(self):
        data = self.builder_data(addon=22)
        with self.assertRaises(models.ObjectDoesNotExist):
            tasks.repackage_jetpack(data)

    def test_bad_file_id(self):
        data = self.builder_data(file_id=234234)
        # Stick the file in the upgrader so it doesn't fail the uuid check.
        self.upgrader.file(234234, {'file': 234234, 'uuid': self.uuid})
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

    def test_cancel(self):
        # Get the data so a row is set in redis.
        data = self.builder_data()
        self.upgrader.cancel()
        eq_(tasks.repackage_jetpack(data), None)

    def test_cancel_only_affects_bulk(self):
        # Get the data so a row is set in redis.
        data = self.builder_data()
        # Clear out everything.
        self.upgrader.cancel()
        # Put the file back in redis.
        self.upgrader.file(self.file.id, {'uuid': self.uuid,
                                          'file': self.file.id,
                                          'version': '1.0b4'})
        # Try to clear again, this should skip the ownerless task above.
        self.upgrader.cancel()
        # The task should still work and return a new file.
        assert tasks.repackage_jetpack(data)

    def test_clear_redis_after_success(self):
        # Get the data so a row is set in redis.
        data = self.builder_data()
        assert tasks.repackage_jetpack(data)
        eq_(self.upgrader.file(self.file.id), {})
        eq_(self.upgrader.version(), None)

    def test_email_sent(self):
        assert tasks.repackage_jetpack(self.builder_data())
        eq_(len(mail.outbox), 1)

    def test_supported_apps(self):
        # Create AppVersions to match what's in the xpi.
        AppVersion.objects.create(application_id=amo.FIREFOX.id, version='3.6')
        AppVersion.objects.create(
            application_id=amo.FIREFOX.id, version='4.0b6')

        # Make sure the new appver matches the old appver.
        new = tasks.repackage_jetpack(self.builder_data()).version
        for old_app in self.file.version.apps.all():
            new_app = new.apps.filter(application=old_app.application)
            eq_(new_app.values_list('min', 'max')[0],
                (old_app.min_id, old_app.max_id))

    def test_block_duplicate_version(self):
        eq_(self.addon.versions.count(), 1)
        assert tasks.repackage_jetpack(self.builder_data())
        eq_(self.addon.versions.count(), 2)

        # Make a new temp file for urlretrieve.
        tmp_file = self.create_temp_file()
        self.urllib.urlretrieve.return_value = (tmp_file.name, None)

        assert not tasks.repackage_jetpack(self.builder_data())
        eq_(self.addon.versions.count(), 2)

    def test_file_on_mirror(self):
        # Make sure the mirror dir is clear.
        shutil.rmtree(os.path.dirname(self.file.mirror_file_path))
        new_file = tasks.repackage_jetpack(self.builder_data())
        assert os.path.exists(new_file.mirror_file_path)

    def test_unreviewed_file_not_on_mirror(self):
        # Make sure the mirror dir is clear.
        shutil.rmtree(os.path.dirname(self.file.mirror_file_path))
        self.file.update(status=amo.STATUS_UNREVIEWED)
        new_file = tasks.repackage_jetpack(self.builder_data())
        assert not os.path.exists(new_file.mirror_file_path)
