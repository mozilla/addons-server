# -*- coding: utf-8 -*-
from nose.tools import eq_

import amo
import amo.tests
from addons.models import AddonPremium

import mkt
from mkt.developers.management.commands import (
    cleanup_addon_premium,
    migrate_free_apps_without_worldwide_aer,
    migrate_geodata
)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestCommandViews(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)

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
            region=mkt.regions.WORLDWIDE.id).count(), 0)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, True)

    def test_no_migration_of_free_apps_without_world_aer_paid_app(self):
        """Paid app users already have the ability to set enable_new_regions
        so we don't want to clobber that.

        """
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.webapp.enable_new_regions, False)
        eq_(self.webapp.addonexcludedregion.filter(
            region=mkt.regions.WORLDWIDE.id).count(), 0)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, False)

    def test_no_migration_of_free_apps_with_world_aer(self):
        eq_(self.webapp.enable_new_regions, False)
        self.webapp.addonexcludedregion.create(region=mkt.regions.WORLDWIDE.id)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, False)

    def test_no_migration_of_free_apps_with_world_aer_already_enabled(self):
        self.webapp.update(enable_new_regions=True)
        self.webapp.addonexcludedregion.create(region=mkt.regions.WORLDWIDE.id)
        migrate_free_apps_without_worldwide_aer.Command().handle()
        eq_(Webapp.objects.no_cache().get(pk=337141).enable_new_regions, True)


class TestMigrateGeodata(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)

    def test_restricted_no_migration_of_paid_apps_exclusions(self):
        self.make_premium(self.webapp)
        self.webapp.addonexcludedregion.create(region=mkt.regions.US.id)
        eq_(self.webapp.geodata.reload().restricted, False)

        migrate_geodata.Command().handle()

        eq_(self.webapp.reload().addonexcludedregion.count(), 1)
        eq_(self.webapp.geodata.reload().restricted, True)

    def test_unrestricted_migration_of_free_apps_exclusions(self):
        self.webapp.addonexcludedregion.create(region=mkt.regions.US.id)
        eq_(self.webapp.geodata.reload().restricted, False)

        migrate_geodata.Command().handle()

        eq_(self.webapp.reload().addonexcludedregion.count(), 0)
        eq_(self.webapp.geodata.reload().restricted, False)

    def test_migration_of_regional_content(self):
        # Exclude in every where except Brazil.
        regions = list(mkt.regions.REGIONS_CHOICES_ID_DICT)
        regions.remove(mkt.regions.BR.id)
        for region in regions:
            self.webapp.addonexcludedregion.create(region=region)

        eq_(self.webapp.geodata.reload().popular_region, None)

        migrate_geodata.Command().handle()

        eq_(self.webapp.reload().addonexcludedregion.count(), 0)
        eq_(self.webapp.geodata.reload().popular_region, mkt.regions.BR.slug)

    def test_migration_of_rated_games(self):
        # This adds a ContentRating for only Brazil, not Germany.
        amo.tests.make_game(self.webapp, rated=True)
        self.webapp.content_ratings.filter(
            ratings_body=mkt.regions.DE.ratingsbody.id).delete()

        regions = (mkt.regions.BR.id, mkt.regions.DE.id)
        for region in regions:
            self.webapp.addonexcludedregion.create(region=region)

        migrate_geodata.Command().handle()

        self.assertSetEqual(self.webapp.reload().addonexcludedregion
                                .values_list('region', flat=True),
                            [mkt.regions.DE.id])

    def test_no_migration_of_unrated_games(self):
        amo.tests.make_game(self.webapp, rated=False)

        regions = (mkt.regions.BR.id, mkt.regions.DE.id)
        for region in regions:
            self.webapp.addonexcludedregion.create(region=region)

        migrate_geodata.Command().handle()

        self.assertSetEqual(self.webapp.reload().addonexcludedregion
                                .values_list('region', flat=True),
                            regions)
