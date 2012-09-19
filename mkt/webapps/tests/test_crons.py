from datetime import datetime, timedelta
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from users.models import UserProfile
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
