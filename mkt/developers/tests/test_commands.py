# -*- coding: utf-8 -*-
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon, AddonPremium
from mkt.constants.regions import WORLDWIDE
from mkt.developers.management.commands import (
    cleanup_addon_premium,
    migrate_free_apps_without_worldwide_aer
)
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


class TestCommandViews(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = self.get_webapp()

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_cleanup_addonpremium(self):
        self.make_premium(self.webapp)
        eq_(AddonPremium.objects.all().count(), 1)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 1)
        self.webapp.update(premium_type=amo.ADDON_FREE)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 0)


class TestMigrateFreeAppsWithoutWorldAER(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)

    def test_migration_of_free_apps_without_world_aer(self):
        eq_(self.webapp.enable_new_regions, False)
        eq_(self.webapp.addonexcludedregion.filter(
            region=WORLDWIDE.id).count(), 0)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, True)

    def test_no_migration_of_free_apps_without_world_aer_paid_app(self):
        """Paid app users already have the ability to set enable_new_regions
        so we don't want to clobber that.

        """
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.webapp.enable_new_regions, False)
        eq_(self.webapp.addonexcludedregion.filter(
            region=WORLDWIDE.id).count(), 0)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, False)

    def test_no_migration_of_free_apps_with_world_aer(self):
        eq_(self.webapp.enable_new_regions, False)
        AER.objects.create(addon=self.webapp, region=WORLDWIDE.id)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, False)

    def test_no_migration_of_free_apps_with_world_aer_already_enabled(self):
        self.webapp.update(enable_new_regions=True)
        AER.objects.create(addon=self.webapp, region=WORLDWIDE.id)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, True)
