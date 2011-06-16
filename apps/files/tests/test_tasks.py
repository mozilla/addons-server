import hashlib
import os
import tempfile
import urllib
import urlparse
import uuid

from django.conf import settings
from django.core import mail
from django.db import models

import mock
import test_utils
from nose.tools import eq_

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from addons.models import Addon
from files import tasks
from files.models import File
from files.utils import JetpackUpgrader


class TestUpgradeJetpacks(test_utils.TestCase):
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
        tasks.start_upgrade([file_.id])
        assert self.urllib2.urlopen.called
        url, args = self.urllib2.urlopen.call_args[0]
        args = dict(urlparse.parse_qsl(args))
        self.assertDictEqual(args, {
            'addon': str(3615),
            'file_id': str(file_.id),
            'priority': 'low',
            'secret': settings.BUILDER_SECRET_KEY,
            'location': file_.get_url_path('', 'builder'),
            'uuid': args['uuid'],  # uuid is random so steal from args.
            'version': '2.1.072.sdk.{sdk_version}',
            'pingback': absolutify(reverse('amo.builder-pingback')),
        })
        eq_(url, settings.BUILDER_UPGRADE_URL)


class TestRepackageJetpack(test_utils.TestCase):
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
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        tmp_file.write(open(self.xpi_path, 'rb').read())
        tmp_file.flush()
        self.urllib.urlretrieve.return_value = (tmp_file.name, None)

        self.upgrader = JetpackUpgrader()
        settings.SEND_REAL_EMAIL = True

        self.uuid = uuid.uuid4().hex

    def builder_data(self, **kw):
        """Generate builder_data response dictionary with sensible defaults."""
        # Tell Redis we're sending to builder.
        self.upgrader.file(self.file.id, {'uuid': self.uuid,
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
        self.upgrader.file(234234, {'uuid': self.uuid})
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
        version = tasks.repackage_jetpack(self.builder_data()).version
        old_apps = self.file.version.compatible_apps
        eq_(version.compatible_apps.keys(), old_apps.keys())
        for app, appver in version.compatible_apps.items():
            eq_(old_apps[app].max, appver.max)
            eq_(old_apps[app].min, appver.min)


def test_parse_version():
    def check(v, expected):
        eq_(tasks.parse_version(v), expected)

    # Start with some normalish version numbers.
    d = (('1.1', '1.1.sdk.{sdk_version}'),
         ('0.2.3', '0.2.3.sdk.{sdk_version}'),
         ('0.2.3-woo', '0.2.3-woo.sdk.{sdk_version}'),
         ('023ab', '023ab.sdk.{sdk_version}'),
         ('0.2.3', '0.2.3.sdk.{sdk_version}'),
    )
    for version, expected in d:
        yield check, version, expected
        # Append .sdk.1.0 to the normal numbers to simulate versions that have
        # already been upgraded in the past. We still get the same template.
        yield check, version + '.sdk.1.0', expected
