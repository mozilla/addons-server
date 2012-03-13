import json

from django.conf import settings
from django.core.management import call_command

import mock
from nose.tools import eq_

import amo
import amo.tests
from devhub.models import ActivityLog
from files.models import File
from users.models import UserProfile
from versions.models import Version
from mkt.webapps.tasks import update_manifests
from mkt.webapps.models import Webapp

original = {
        "version": "0.1",
        "name": "MozillaBall",
        "description": "Exciting Open Web development action!",
        "installs_allowed_from": [
            "https://appstore.mozillalabs.com",
        ],
    }

new = {
        "version": "1.0",
        "name": "MozillaBall",
        "description": "Exciting Open Web development action!",
        "installs_allowed_from": [
            "https://appstore.mozillalabs.com",
        ],
    }

ohash = 'sha256:fc11fba25f251d64343a7e8da4dfd812a57a121e61eb53c78c567536ab39b10d'
nhash = 'sha256:912731929d8336beb88052f2fd838243d1534d3acef81796606e78312601e66b'


class TestUpdateManifest(amo.tests.TestCase):
    fixtures = ('base/platforms',)

    def setUp(self):
        UserProfile.objects.create(id=settings.TASK_USER_ID)
        self.addon = Webapp.objects.create(type=amo.ADDON_WEBAPP)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        hash=ohash,
                                        platform_id=1)

        # This is the hash to set the get_content_hash to, for showing
        # that the webapp has been updated.
        self._hash = nhash
        self._data = json.dumps(new)

    def _write(self, filename, url):
        # FileUpload wants a file with some data in it, this does it.
        open(filename, 'w').write(self._data)
        return self._hash

    @mock.patch('mkt.webapps.tasks._get_content_hash')
    def _run(self, _get_content_hash):
        # Will run the task and will act depending upon how you've set hash.
        _get_content_hash.side_effect = self._write
        update_manifests(ids=(self.addon.pk,))

    def test_new_version(self):
        eq_(self.addon.versions.count(), 1)
        old_version = self.addon.current_version
        old_file = self.addon.get_latest_file
        self._run()

        # Test that our new version looks good
        new = Webapp.objects.get(pk=self.addon.pk)
        eq_(new.versions.count(), 2)
        assert new.current_version != old_version, 'Version not updated'
        assert new.get_latest_file() != old_file, 'Version not updated'

    def test_new_version_multiple(self):
        self._run()
        self._data = self._data.replace('1.0', '1.1')
        self._hash = 'foo'
        self._run()

        new = Webapp.objects.get(pk=self.addon.pk)
        eq_(new.versions.count(), 3)

    def test_not_log(self):
        self._hash = ohash
        self._run()
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 0)

    def test_log(self):
        self._run()
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 1)

    @mock.patch('mkt.webapps.tasks._get_content_hash')
    def test_error(self, _get_content_hash):
        _get_content_hash.side_effect = Exception()
        update_manifests(ids=(self.addon.pk,))
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 0)

    @mock.patch('mkt.webapps.tasks.update_manifests')
    def test_ignore_not_webapp(self, update_manifests):
        self.addon.update(type=amo.ADDON_EXTENSION)
        call_command('process_addons', task='update_manifests')
        assert not update_manifests.call_args

    @mock.patch('mkt.webapps.tasks.update_manifests')
    def test_ignore_disabled(self, update_manifests):
        self.addon.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='update_manifests')
        assert not update_manifests.call_args

    @mock.patch('mkt.webapps.tasks.update_manifests')
    def test_get_webapp(self, update_manifests):
        call_command('process_addons', task='update_manifests')
        assert not update_manifests.call_args
