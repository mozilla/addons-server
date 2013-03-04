# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management import call_command

import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from django.core.management.base import CommandError
from lib.es.management.commands.reindex import flag_database, unflag_database
from users.models import UserProfile
from mkt.site.fixtures import fixture
from mkt.webapps.cron import clean_old_signed, update_weekly_downloads
from mkt.webapps.models import Installed, Webapp


class TestWeeklyDownloads(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = Webapp.objects.create(type=amo.ADDON_WEBAPP)
        self.user = UserProfile.objects.get(pk=999)

    def get_webapp(self):
        return Webapp.objects.get(pk=self.addon.pk)

    def add_install(self, addon=None, user=None, created=None):
        install = Installed.objects.create(addon=addon or self.addon,
                                           user=user or self.user)
        if created:
            install.update(created=created)
        return install

    def test_weekly_downloads(self):
        eq_(self.get_webapp().weekly_downloads, 0)
        self.add_install()
        self.add_install(user=UserProfile.objects.get(pk=10482),
                         created=datetime.today() - timedelta(days=2))
        update_weekly_downloads()
        eq_(self.get_webapp().weekly_downloads, 2)

    def test_weekly_downloads_flagged(self):
        eq_(self.get_webapp().weekly_downloads, 0)
        self.add_install()
        self.add_install(user=UserProfile.objects.get(pk=10482),
                         created=datetime.today() - timedelta(days=2))

        flag_database('new', 'old', 'alias')
        try:
            # Should fail.
            self.assertRaises(CommandError, update_weekly_downloads)
            eq_(self.get_webapp().weekly_downloads, 0)

            # Should work with the environ flag.
            os.environ['FORCE_INDEXING'] = '1'
            update_weekly_downloads()
        finally:
            unflag_database()
            del os.environ['FORCE_INDEXING']

        eq_(self.get_webapp().weekly_downloads, 2)

    def test_recently(self):
        self.add_install(created=datetime.today() - timedelta(days=6))
        update_weekly_downloads()
        eq_(self.get_webapp().weekly_downloads, 1)

    def test_long_ago(self):
        self.add_install(created=datetime.today() - timedelta(days=8))
        update_weekly_downloads()
        eq_(self.get_webapp().weekly_downloads, 0)

    def test_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.add_install()
        update_weekly_downloads()
        eq_(Addon.objects.get(pk=self.addon.pk).weekly_downloads, 0)


class TestCleanup(amo.tests.TestCase):

    def setUp(self):
        self.file = os.path.join(settings.SIGNED_APPS_REVIEWER_PATH,
                                 '1', 'x.z')

    def test_not_cleaned(self):
        storage.open(self.file, 'w')
        clean_old_signed()
        assert storage.exists(self.file)

    def test_cleaned(self):
        storage.open(self.file, 'w')
        clean_old_signed(-60)
        assert not storage.exists(self.file)


@mock.patch('lib.crypto.packaged.sign_app')
class TestSignApps(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Addon.objects.get(id=337141)
        self.app.update(is_packaged=True)
        self.app2 = amo.tests.app_factory(
            name='Mozillaball ょ', app_slug='test',
            is_packaged=True, version_kw={'version': '1.0',
                                          'created': None})
        self.app3 = amo.tests.app_factory(
            name='Test app 3', app_slug='test3', status=amo.STATUS_REJECTED,
            is_packaged=True, version_kw={'version': '1.0',
                                          'created': None})

    def test_by_webapp(self, sign_mock):
        v1 = self.app.get_version()
        call_command('sign_apps', webapps=str(v1.pk))
        file1 = v1.all_files[0]
        assert sign_mock.called_with(((file1.file_path,
                                       file1.signed_file_path),))

    def test_all(self, sign_mock):
        v1 = self.app.get_version()
        v2 = self.app2.get_version()
        call_command('sign_apps')
        file1 = v1.all_files[0]
        file2 = v2.all_files[0]
        eq_(len(sign_mock.mock_calls), 2)
        sign_mock.assert_has_calls([
            mock.call(file1.file_path,
                      file1.signed_file_path, False),
            mock.call(file2.file_path,
                      file2.signed_file_path, False)],
            any_order=True)
