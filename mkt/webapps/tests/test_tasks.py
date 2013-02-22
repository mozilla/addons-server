# -*- coding: utf-8 -*-
import datetime
import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management import call_command

import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from devhub.models import ActivityLog
from editors.models import RereviewQueue
from files.models import File, FileUpload
from users.models import UserProfile
from versions.models import Version

from mkt.webapps.models import Webapp
from mkt.webapps.tasks import update_manifests


original = {
    "version": "0.1",
    "default_locale": "en-US",
    "name": "MozillaBall",
    "description": "Exciting Open Web development action!",
    "icons": {
        "16": "http://test.com/icon-16.png",
        "48": "http://test.com/icon-48.png",
        "128": "http://test.com/icon-128.png"
    },
    "installs_allowed_from": [
        "*",
    ],
    "locales": {
        "de": {
            "name": "Mozilla Kugel"
        },
        "fr": {
            "description": "Testing name-less locale"
        }
    }
}


new = {
    "version": "1.0",
    "default_locale": "en-US",
    "name": "MozillaBall",
    "description": "Exciting Open Web development action!",
    "icons": {
        "16": "http://test.com/icon-16.png",
        "48": "http://test.com/icon-48.png",
        "128": "http://test.com/icon-128.png"
    },
    "installs_allowed_from": [
        "*",
    ],
    "locales": {
        "de": {
            "name": "Mozilla Kugel"
        },
        "fr": {
            "description": "Testing name-less locale"
        }
    }
}


ohash = ('sha256:'
         'fc11fba25f251d64343a7e8da4dfd812a57a121e61eb53c78c567536ab39b10d')
nhash = ('sha256:'
         '409fbe87dca5a4a7937e3dea27b69cb3a3d68caf39151585aef0c7ab46d8ee1e')


class TestUpdateManifest(amo.tests.TestCase):
    fixtures = ('base/platforms',)

    def setUp(self):
        UserProfile.objects.get_or_create(id=settings.TASK_USER_ID)

        # Not using app factory since it creates translations with an invalid
        # locale of "en-us".
        self.addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(
            version=self.version, hash=ohash, status=amo.STATUS_PUBLIC,
            filename='%s-%s' % (self.addon.id, self.version.id))

        self.addon.name = {
            'en-US': 'MozillaBall',
            'de': 'Mozilla Kugel',
        }
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.save()

        ActivityLog.objects.all().delete()

        with storage.open(self.file.file_path, 'w') as fh:
            fh.write(json.dumps(original))

        # This is the hash to set the get_content_hash to, for showing
        # that the webapp has been updated.
        self._hash = nhash
        self.new = new.copy()

        urlopen_patch = mock.patch('urllib2.urlopen')
        self.urlopen_mock = urlopen_patch.start()
        self.addCleanup(urlopen_patch.stop)

        self.response_mock = mock.Mock()
        self.response_mock.read.return_value = self._data()
        self.response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = self.response_mock

        p = mock.patch('mkt.webapps.tasks.validator')
        validator = p.start()
        validator.return_value = {}
        self.patches = [p]

    def tearDown(self):
        super(TestUpdateManifest, self).tearDown()
        for p in self.patches:
            p.stop()

    @mock.patch('mkt.webapps.tasks._get_content_hash')
    def _run(self, _get_content_hash, **kw):
        # Will run the task and will act depending upon how you've set hash.
        _get_content_hash.return_value = self._hash
        update_manifests(ids=(self.addon.pk,), **kw)

    def _data(self):
        return json.dumps(self.new)

    @mock.patch('mkt.webapps.models.copy_stored_file')
    def test_new_version_not_created(self, _copy_stored_file):
        # Test that update_manifest doesn't create multiple versions/files.
        eq_(self.addon.versions.count(), 1)
        old_version = self.addon.current_version
        old_file = self.addon.get_latest_file()
        self._run()

        new = Webapp.objects.get(pk=self.addon.pk)
        version = new.current_version
        file = new.get_latest_file()

        # Test that our new version looks good
        eq_(new.versions.count(), 1)
        assert version == old_version, 'Version created'
        assert file == old_file, 'File created'

        path = FileUpload.objects.all()[0].path
        _copy_stored_file.assert_called_with(path,
                                             os.path.join(version.path_prefix,
                                                          file.filename))

    def test_version_updated(self):
        self._run()
        self.new['version'] = '1.1'
        self.response_mock.read.return_value = self._data()
        self._hash = 'foo'
        self._run()

        new = Webapp.objects.get(pk=self.addon.pk)
        eq_(new.versions.latest().version, '1.1')

    def test_not_log(self):
        self._hash = ohash
        self._run()
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 0)

    def test_log(self):
        self._run()
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 1)

    @mock.patch('mkt.webapps.tasks._update_manifest')
    def test_ignore_not_webapp(self, mock_):
        self.addon.update(type=amo.ADDON_EXTENSION)
        call_command('process_addons', task='update_manifests')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_manifest')
    def test_pending(self, mock_):
        self.addon.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='update_manifests')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._update_manifest')
    def test_ignore_disabled(self, mock_):
        self.addon.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='update_manifests')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_manifest')
    def test_ignore_packaged(self, mock_):
        self.addon.update(is_packaged=True)
        call_command('process_addons', task='update_manifests')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_manifest')
    def test_get_webapp(self, mock_):
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        call_command('process_addons', task='update_manifests')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    def test_update_manifest(self, retry, fetch):
        fetch.return_value = '{}'
        update_manifests(ids=(self.addon.pk,))
        assert not retry.called

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    def test_manifest_fetch_fail(self, retry, fetch):
        later = datetime.datetime.now() + datetime.timedelta(seconds=3600)
        fetch.side_effect = RuntimeError
        update_manifests(ids=(self.addon.pk,))
        retry.assert_called()
        # Not using assert_called_with b/c eta is a datetime.
        eq_(retry.call_args[1]['args'], ([self.addon.pk],))
        eq_(retry.call_args[1]['kwargs'], {'check_hash': True,
                                           'retries': {self.addon.pk: 1}})
        self.assertCloseToNow(retry.call_args[1]['eta'], later)
        eq_(retry.call_args[1]['max_retries'], 4)

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    def test_manifest_fetch_3x_fail(self, retry, fetch):
        fetch.side_effect = RuntimeError
        update_manifests(ids=(self.addon.pk,), retries={self.addon.pk: 2})
        assert not retry.called
        assert RereviewQueue.objects.filter(addon=self.addon).exists()

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_manifest_name_change_rereview(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        n['name'] = 'Mozilla Ball Ultimate Edition'
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 1)
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_manifest_locale_name_add_rereview(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        n['locales'] = {'es': {'name': 'eso'}}
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 1)
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)
        log = ActivityLog.objects.filter(
            action=amo.LOG.REREVIEW_MANIFEST_CHANGE.id)[0]
        eq_(log.details.get('comments'),
            u'Locales added: "eso" (es).')

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_manifest_locale_name_change_rereview(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        n['locales'] = {'de': {'name': 'Bippity Bop'}}
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 1)
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)
        log = ActivityLog.objects.filter(
            action=amo.LOG.REREVIEW_MANIFEST_CHANGE.id)[0]
        eq_(log.details.get('comments'),
            u'Locales updated: "Mozilla Kugel" -> "Bippity Bop" (de).')

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_manifest_default_locale_change(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        n['name'] = u'Mozilla Balón'
        n['default_locale'] = 'es'
        n['locales'] = {'en-US': {'name': 'MozillaBall'}}
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 1)
        eq_(self.addon.reload().default_locale, 'es')
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)
        log = ActivityLog.objects.filter(
            action=amo.LOG.REREVIEW_MANIFEST_CHANGE.id)[0]
        eq_(log.details.get('comments'),
            u'Manifest name changed from "MozillaBall" to "Mozilla Balón". '
            u'Default locale changed from "en-US" to "es". '
            u'Locales added: "Mozilla Balón" (es).')

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_manifest_locale_name_removal_no_rereview(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        del n['locales']['de']
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 0)
        # Log for manifest update.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 1)

    @mock.patch('mkt.webapps.tasks._open_manifest')
    def test_force_rereview(self, open_manifest):
        # Mock original manifest file lookup.
        open_manifest.return_value = original
        # Mock new manifest with name change.
        n = new.copy()
        n['name'] = 'Mozilla Ball Ultimate Edition'
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(n)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        # We're setting the hash to the same value.
        self.file.update(hash=nhash)

        eq_(RereviewQueue.objects.count(), 0)
        self._run(check_hash=False)

        # We should still get a rereview since we bypassed the manifest check.
        eq_(RereviewQueue.objects.count(), 1)

        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)
