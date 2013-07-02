# -*- coding: utf-8 -*-
import datetime
import json
import os
import stat

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management import call_command
from django.forms import ValidationError

import mock
from nose.tools import eq_, ok_

import amo
import amo.tests
from addons.models import Addon
from devhub.models import ActivityLog
from editors.models import RereviewQueue
from files.models import File, FileUpload
from users.models import UserProfile
from versions.models import Version

from mkt.site.fixtures import fixture
from mkt.webapps.models import AppFeatures, Webapp
from mkt.webapps.tasks import (dump_app, update_developer_name, update_features,
                               update_manifests, zip_apps)


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
    fixtures = ('base/platforms',)

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
        eq_(retry.call_args[1]['max_retries'], 4)

    @mock.patch('mkt.webapps.tasks._fetch_manifest')
    @mock.patch('mkt.webapps.tasks.update_manifests.retry')
    def test_manifest_fetch_3x_fail(self, retry, fetch):
        fetch.side_effect = RuntimeError
        update_manifests(ids=(self.addon.pk,), retries={self.addon.pk: 2})
        assert not retry.called
        assert RereviewQueue.objects.filter(addon=self.addon).exists()

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    def test_manifest_name_change_rereview(self, _manifest):
        # Mock original manifest file lookup.
        _manifest.return_value = original
        # Mock new manifest with name change.
        self.new['name'] = 'Mozilla Ball Ultimate Edition'
        response_mock = mock.Mock()
        response_mock.read.return_value = json.dumps(self.new)
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
        eq_(result['id'], str(337141))

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

    @mock.patch('mkt.webapps.tasks.dump_app')
    def test_public(self, dump_app):
        call_command('process_addons', task='dump_apps')
        assert dump_app.called


class TestUpdateFeatures(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.create_switch('buchets')

        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        # Note: the app files are wrong, since we now have a packaged app, but
        # it doesn't matter since we are mocking everything, we'll never touch
        # the files.

        p = mock.patch('mkt.webapps.tasks.run_validator')
        self.mock_validator = p.start()
        self.mock_validator.return_value = json.dumps({
            'feature_profile': {}
        })
        self.patches = [p]

    def tearDown(self):
        super(TestUpdateFeatures, self).tearDown()
        for p in self.patches:
            p.stop()

    @mock.patch('mkt.webapps.tasks._update_features')
    def test_ignore_not_webapp(self, mock_):
        self.app.update(type=amo.ADDON_EXTENSION)
        call_command('process_addons', task='update_features')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_features')
    def test_pending(self, mock_):
        self.app.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='update_features')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._update_features')
    def test_public_waiting(self, mock_):
        self.app.update(status=amo.STATUS_PUBLIC_WAITING)
        call_command('process_addons', task='update_features')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._update_features')
    def test_ignore_disabled(self, mock_):
        self.app.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='update_features')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_features')
    def test_ignore_non_packaged(self, mock_):
        self.app.update(is_packaged=False)
        call_command('process_addons', task='update_features')
        assert not mock_.called

    def test_ignore_no_current_version(self):
        self.app.current_version.all_files[0].update(status=amo.STATUS_DISABLED)
        self.app.update_version()
        update_features(ids=(self.app.pk,))
        assert not self.mock_validator.called

    def test_ignore_non_empty_features_profile(self):
        version = self.app.current_version
        version.features.update(has_sms=True)
        update_features(ids=(self.app.pk,))
        assert not self.mock_validator.called

    def test_validator(self):
        update_features(ids=(self.app.pk,))
        assert self.mock_validator.called
        features = self.app.current_version.features.to_dict()
        eq_(AppFeatures().to_dict(), features)

    def test_validator_with_results(self):
        feature_profile = ['APPS', 'ACTIVITY']
        self.mock_validator.return_value = json.dumps({
            'feature_profile': feature_profile
        })
        update_features(ids=(self.app.pk,))
        assert self.mock_validator.called
        features = self.app.current_version.features.to_dict()
        eq_(features['has_apps'], True)
        eq_(features['has_activity'], True)
        eq_(features['has_sms'], False)

    def test_validator_with_results_existing_empty_profile(self):
        feature_profile = ['APPS', 'ACTIVITY']
        self.mock_validator.return_value = json.dumps({
            'feature_profile': feature_profile
        })
        version = self.app.current_version
        eq_(AppFeatures.objects.count(), 1)
        eq_(version.features.to_list(), [])
        update_features(ids=(self.app.pk,))
        assert self.mock_validator.called
        eq_(AppFeatures.objects.count(), 1)

        # Features are cached on the version, therefore reload the app since we
        # were using the same instance as before.
        self.app.reload()
        features = self.app.current_version.features.to_dict()
        eq_(features['has_apps'], True)
        eq_(features['has_activity'], True)
        eq_(features['has_sms'], False)


class TestUpdateDeveloperName(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)

    @mock.patch('mkt.webapps.tasks._update_developer_name')
    def test_ignore_not_webapp(self, mock_):
        self.app.update(type=amo.ADDON_EXTENSION)
        call_command('process_addons', task='update_developer_name')
        assert not mock_.called

    @mock.patch('mkt.webapps.tasks._update_developer_name')
    def test_pending(self, mock_):
        self.app.update(status=amo.STATUS_PENDING)
        call_command('process_addons', task='update_developer_name')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._update_developer_name')
    def test_public_waiting(self, mock_):
        self.app.update(status=amo.STATUS_PUBLIC_WAITING)
        call_command('process_addons', task='update_developer_name')
        assert mock_.called

    @mock.patch('mkt.webapps.tasks._update_developer_name')
    def test_ignore_disabled(self, mock_):
        self.app.update(status=amo.STATUS_DISABLED)
        call_command('process_addons', task='update_developer_name')
        assert not mock_.called

    @mock.patch('files.utils.WebAppParser.parse')
    def test_ignore_no_current_version(self, mock_parser):
        self.app.current_version.all_files[0].update(status=amo.STATUS_DISABLED)
        self.app.update_version()
        update_developer_name(ids=(self.app.pk,))
        assert not mock_parser.called

    @mock.patch('files.utils.WebAppParser.parse')
    def test_ignore_if_existing_developer_name(self, mock_parser):
        version = self.app.current_version
        version.update(_developer_name=u"Mï")
        update_developer_name(ids=(self.app.pk,))
        assert not mock_parser.called

    @mock.patch('files.utils.WebAppParser.parse')
    def test_update_developer_name(self, mock_parser):
        mock_parser.return_value = {
            'developer_name': u'New Dêv'
        }
        self.app.current_version.update(_developer_name='')
        update_developer_name(ids=(self.app.pk,))
        version = self.app.current_version.reload()
        eq_(version._developer_name, u'New Dêv')
        eq_(version.developer_name, u'New Dêv')

    @mock.patch('files.utils.WebAppParser.parse')
    @mock.patch('mkt.webapps.tasks._log')
    def test_update_developer_name_validation_error(self, _log, mock_parser):
        mock_parser.side_effect = ValidationError('dummy validation error')
        self.app.current_version.update(_developer_name='')
        update_developer_name(ids=(self.app.pk,))
        assert _log.called_with(337141, u'Webapp manifest can not be parsed')

        version = self.app.current_version.reload()
        eq_(version._developer_name, '')


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
