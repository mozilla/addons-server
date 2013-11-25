# -*- coding: utf-8 -*-
import datetime
import hashlib
import json
import os
import stat

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core import mail
from django.core.management import call_command
from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_, ok_

import amo
import amo.tests
from addons.models import Addon, AddonUser
from amo.helpers import absolutify
from devhub.models import ActivityLog
from editors.models import RereviewQueue
from files.models import File, FileUpload
from users.models import UserProfile
from versions.models import Version

from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from mkt.webapps.tasks import (dump_app, dump_user_installs,
                               notify_developers_of_failure, update_manifests,
                               zip_apps)


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
    },
    "developer": {
        "name": "Mozilla",
        "url": "http://www.mozilla.org/"
    }
}


ohash = ('sha256:'
         'fc11fba25f251d64343a7e8da4dfd812a57a121e61eb53c78c567536ab39b10d')
nhash = ('sha256:'
         '409fbe87dca5a4a7937e3dea27b69cb3a3d68caf39151585aef0c7ab46d8ee1e')


class TestUpdateManifest(amo.tests.TestCase):
    fixtures = ('base/platforms', 'base/users')

    def setUp(self):

        UserProfile.objects.get_or_create(id=settings.TASK_USER_ID)

        # Not using app factory since it creates translations with an invalid
        # locale of "en-us".
        self.addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.version = Version.objects.create(addon=self.addon,
                                              _developer_name='Mozilla')
        self.file = File.objects.create(
            version=self.version, hash=ohash, status=amo.STATUS_PUBLIC,
            filename='%s-%s' % (self.addon.id, self.version.id))

        self.addon.name = {
            'en-US': 'MozillaBall',
            'de': 'Mozilla Kugel',
        }
        self.addon.status = amo.STATUS_PUBLIC
        self.addon.manifest_url = 'http://nowhere.allizom.org/manifest.webapp'
        self.addon.save()

        AddonUser.objects.create(addon=self.addon,
                                 user=UserProfile.objects.get(pk=999))

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
        self.response_mock.getcode.return_value = 200
        self.response_mock.read.return_value = self._data()
        self.response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = self.response_mock

        p = mock.patch('mkt.webapps.tasks.validator')
        self.validator = p.start()
        self.validator.return_value = {}
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

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    @mock.patch('mkt.webapps.models.copy_stored_file')
    def test_new_version_not_created(self, _copy_stored_file, _manifest_json):
        # Test that update_manifest doesn't create multiple versions/files.
        eq_(self.addon.versions.count(), 1)
        old_version = self.addon.current_version
        old_file = self.addon.get_latest_file()
        self._run()

        app = Webapp.objects.get(pk=self.addon.pk)
        version = app.current_version
        file = app.get_latest_file()

        # Test that our new version looks good.
        eq_(app.versions.count(), 1)
        assert version == old_version, 'Version created'
        assert file == old_file, 'File created'

        path = FileUpload.objects.all()[0].path
        _copy_stored_file.assert_called_with(path,
                                             os.path.join(version.path_prefix,
                                                          file.filename))
        _manifest_json.assert_called_with(file)

    def test_version_updated(self):
        self._run()
        self.new['version'] = '1.1'
        self.response_mock.read.return_value = self._data()
        self._hash = 'foo'
        self._run()

        app = Webapp.objects.get(pk=self.addon.pk)
        eq_(app.versions.latest().version, '1.1')

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
    def test_waiting(self, mock_):
        self.addon.update(status=amo.STATUS_PUBLIC_WAITING)
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
        eq_(retry.call_args[1]['max_retries'], 5)
        eq_(len(mail.outbox), 0)

    def test_notify_failure_lang(self):
        user1 = UserProfile.objects.get(pk=999)
        user2 = UserProfile.objects.get(pk=10482)
        AddonUser.objects.create(addon=self.addon, user=user2)
        user1.update(lang='de')
        user2.update(lang='en')
        notify_developers_of_failure(self.addon, 'blah')
        eq_(len(mail.outbox), 2)
        ok_(u'Mozilla Kugel' in mail.outbox[0].subject)
        ok_(u'MozillaBall' in mail.outbox[1].subject)

    def test_notify_failure_with_rereview(self):
        RereviewQueue.flag(self.addon, amo.LOG.REREVIEW_MANIFEST_CHANGE,
                           'This app is flagged!')
        notify_developers_of_failure(self.addon, 'blah')
        eq_(len(mail.outbox), 0)

    def test_notify_failure_not_public(self):
        self.addon.update(status=amo.STATUS_PENDING)
        notify_developers_of_failure(self.addon, 'blah')
        eq_(len(mail.outbox), 0)

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    def test_manifest_fetch_3rd_attempt(self, retry, fetch):
        fetch.side_effect = RuntimeError
        update_manifests(ids=(self.addon.pk,), retries={self.addon.pk: 2})
        # We already tried twice before, this is the 3rd attempt,
        # We should notify the developer that something is wrong.
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        ok_(msg.subject.startswith('Issue with your app'))
        expected = u'Failed to get manifest from %s' % self.addon.manifest_url
        ok_(expected in msg.body)
        ok_(settings.MKT_SUPPORT_EMAIL in msg.body)

        # We should have scheduled a retry.
        assert retry.called

        # We shouldn't have put the app in the rereview queue yet.
        assert not RereviewQueue.objects.filter(addon=self.addon).exists()

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    @mock.patch('mkt.webapps.tasks.notify_developers_of_failure')
    def test_manifest_fetch_4th_attempt(self, notify, retry, fetch):
        fetch.side_effect = RuntimeError
        update_manifests(ids=(self.addon.pk,), retries={self.addon.pk: 3})
        # We already tried 3 times before, this is the 4th and last attempt,
        # we shouldn't retry anymore, instead we should just add the app to
        # the re-review queue. We shouldn't notify the developer either at this
        # step, it should have been done before already.
        assert not notify.called
        assert not retry.called
        assert RereviewQueue.objects.filter(addon=self.addon).exists()

    def test_manifest_validation_failure(self):
        # We are already mocking validator, but this test needs to make sure
        # it actually saves our custom validation result, so add that.
        def side_effect(upload_id, **kwargs):
            upload = FileUpload.objects.get(pk=upload_id)
            upload.validation = json.dumps(validation_results)
            upload.save()

        validation_results = {
            'errors': 1,
            'messages': [{
                'context': None,
                'uid': 'whatever',
                'column': None,
                'id': ['webapp', 'detect_webapp', 'parse_error'],
                'file': '',
                'tier': 1,
                'message': 'JSON Parse Error',
                'type': 'error',
                'line': None,
                'description': 'The webapp extension could not be parsed due '
                               'to a syntax error in the JSON.'
            }]
        }
        self.validator.side_effect = side_effect

        eq_(RereviewQueue.objects.count(), 0)

        self._run()

        eq_(RereviewQueue.objects.count(), 1)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        upload = FileUpload.objects.get()
        validation_url = absolutify(reverse(
            'mkt.developers.upload_detail', args=[upload.uuid]))
        ok_(msg.subject.startswith('Issue with your app'))
        ok_(validation_results['messages'][0]['message'] in msg.body)
        ok_(validation_url in msg.body)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_name_change_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['name'] = 'Mozilla Ball Ultimate Edition'
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(self.new)
        response_mock.getcode.return_value = 200
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 1)
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_locale_name_add_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['locales'] = {'es': {'name': 'eso'}}
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
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

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_locale_name_change_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['locales'] = {'de': {'name': 'Bippity Bop'}}
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
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

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_default_locale_change(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['name'] = u'Mozilla Balón'
        self.new['default_locale'] = 'es'
        self.new['locales'] = {'en-US': {'name': 'MozillaBall'}}
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
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

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_locale_name_removal_no_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        # Note: Not using `del` b/c copy doesn't copy nested structures.
        self.new['locales'] = {
            'fr': {'description': 'Testing name-less locale'}}
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        eq_(RereviewQueue.objects.count(), 0)
        self._run()
        eq_(RereviewQueue.objects.count(), 0)
        # Log for manifest update.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 1)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_force_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['name'] = 'Mozilla Ball Ultimate Edition'
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
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

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_support_locales_change(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['locales'].update({'es': {'name': u'Mozilla Balón'}})
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        self._run()
        ver = self.version.reload()
        eq_(ver.supported_locales, 'de,es,fr')

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_support_developer_change(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with developer name change.
        self.new['developer']['name'] = 'Allizom'
        response_mock = mock.Mock()
        response_mock.getcode.return_value = 200
        response_mock.read.return_value = json.dumps(self.new)
        response_mock.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        self.urlopen_mock.return_value = response_mock

        self._run()
        ver = self.version.reload()
        eq_(ver.developer_name, 'Allizom')

        # We should get a re-review because of the developer name change.
        eq_(RereviewQueue.objects.count(), 1)
        # 2 logs: 1 for manifest update, 1 for re-review trigger.
        eq_(ActivityLog.objects.for_apps(self.addon).count(), 2)


class TestDumpApps(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def test_dump_app(self):
        fn = dump_app(337141)
        result = json.load(open(fn, 'r'))
        eq_(result['id'], 337141)

    def test_zip_apps(self):
        dump_app(337141)
        fn = zip_apps()
        for f in ['license.txt', 'readme.txt']:
            ok_(os.path.exists(os.path.join(settings.DUMPED_APPS_PATH, f)))
        ok_(os.stat(fn)[stat.ST_SIZE])

    @mock.patch('mkt.webapps.tasks.dump_app')
    def test_not_public(self, dump_app):
        app = Addon.objects.get(pk=337141)
        app.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='dump_apps')
        assert not dump_app.called

    def test_removed(self):
        # At least one public app must exist for dump_apps to run.
        amo.tests.app_factory(name="second app", status=amo.STATUS_PUBLIC)
        app_path = os.path.join(settings.DUMPED_APPS_PATH, 'apps', '337',
                                '337141.json')
        app = Addon.objects.get(pk=337141)
        app.update(status=amo.STATUS_PUBLIC)
        call_command('process_addons', task='dump_apps')
        assert os.path.exists(app_path)

        app.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='dump_apps')
        assert not os.path.exists(app_path)

    @mock.patch('mkt.webapps.tasks.dump_app')
    def test_public(self, dump_app):
        call_command('process_addons', task='dump_apps')
        assert dump_app.called


class TestDumpUserInstalls(amo.tests.TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        # Create a user install.
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.app.installed.create(user=self.user)
        self.hash = hashlib.sha256('%s%s' % (str(self.user.pk),
                                             settings.SECRET_KEY)).hexdigest()
        self.path = os.path.join(settings.DUMPED_USERS_PATH, 'users',
                                 self.hash[0], '%s.json' % self.hash)

    def dump_and_load(self):
        dump_user_installs([self.user.pk])
        return json.load(open(self.path, 'r'))

    def test_dump_user_installs(self):
        data = self.dump_and_load()
        eq_(data['user'], self.hash)
        eq_(data['region'], self.user.region)
        eq_(data['lang'], self.user.lang)
        installed = data['installed_apps'][0]
        eq_(installed['id'], self.app.id)
        eq_(installed['slug'], self.app.app_slug)
        self.assertCloseToNow(
            datetime.datetime.strptime(installed['installed'],
                                       '%Y-%m-%dT%H:%M:%S'),
            datetime.datetime.utcnow())

    def test_dump_exludes_deleted(self):
        """We can't recommend deleted apps, so don't include them."""
        app = amo.tests.app_factory()
        app.installed.create(user=self.user)
        app.delete()

        data = self.dump_and_load()
        eq_(len(data['installed_apps']), 1)
        installed = data['installed_apps'][0]
        eq_(installed['id'], self.app.id)


class TestFixMissingIcons(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)

    @mock.patch('mkt.webapps.tasks._fix_missing_icons')
    def test_ignore_not_webapp(self, mock_):
        self.app.update(type=amo.ADDON_EXTENSION)
        call_command('process_addons', task='fix_missing_icons')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._fix_missing_icons')
    def test_pending(self, mock_):
        self.app.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='fix_missing_icons')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._fix_missing_icons')
    def test_public_waiting(self, mock_):
        self.app.update(status=amo.STATUS_PUBLIC_WAITING)
        call_command('process_addons', task='fix_missing_icons')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._fix_missing_icons')
    def test_ignore_disabled(self, mock_):
        self.app.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='fix_missing_icons')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks.fetch_icon')
    @mock.patch('mkt.webapps.tasks._log')
    @mock.patch('mkt.webapps.tasks.storage.exists')
    def test_for_missing_size(self, exists, _log, fetch_icon):
        exists.return_value = False
        call_command('process_addons', task='fix_missing_icons')

        # We are checking two sizes, but since the 64 has already failed for
        # this app, we should only have called exists() once, and we should
        # never have logged that the 128 icon is missing.
        eq_(exists.call_count, 1)
        assert _log.any_call(337141, 'Webapp is missing icon size 64')
        assert _log.any_call(337141, 'Webapp is missing icon size 128')
        assert fetch_icon.called
