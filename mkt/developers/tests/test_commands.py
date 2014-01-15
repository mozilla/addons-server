# -*- coding: utf-8 -*-
from nose.tools import eq_

import amo
import amo.tests
from addons.models import AddonPremium

import mkt
from mkt.developers.management.commands import (cleanup_addon_premium,
                                                exclude_games, migrate_geodata)
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
        # Exclude in everywhere except Brazil.
        regions = list(mkt.regions.REGIONS_CHOICES_ID_DICT)
        regions.remove(mkt.regions.BR.id)
        for region in regions:
            self.webapp.addonexcludedregion.create(region=region)

        eq_(self.webapp.geodata.reload().popular_region, None)

        migrate_geodata.Command().handle()

        self.assertSetEqual(self.webapp.reload().addonexcludedregion
                                .values_list('region', flat=True),
                            [mkt.regions.CN.id])
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


class TestExcludeUnratedGames(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)
        self.br = mkt.regions.BR.id
        self.de = mkt.regions.DE.id

    def _assert_listed(self, region):
        assert not self.webapp.addonexcludedregion.filter(
            region=region).exists()

    def _assert_excluded(self, region):
        assert self.webapp.addonexcludedregion.filter(region=region).exists()

    def test_exclude_unrated(self):
        amo.tests.make_game(self.webapp, rated=False)

        exclude_games.Command().handle('br')
        self._assert_excluded(self.br)
        self._assert_listed(self.de)

    def test_dont_exclude_non_game(self):
        exclude_games.Command().handle('br')
        self._assert_listed(self.br)
        self._assert_listed(self.de)

    def test_dont_exclude_rated(self):
        amo.tests.make_game(self.webapp, rated=True)

        exclude_games.Command().handle('br')
        self._assert_listed(self.br)

    def test_germany_case_generic(self):
        amo.tests.make_game(self.webapp, rated=False)
        self.webapp.set_content_ratings({
            mkt.ratingsbodies.GENERIC: mkt.ratingsbodies.GENERIC_18
        })

        exclude_games.Command().handle('de')
        self._assert_listed(self.de)

    def test_germany_case_usk(self):
        amo.tests.make_game(self.webapp, rated=False)
        self.webapp.set_content_ratings({
            mkt.ratingsbodies.USK: mkt.ratingsbodies.USK_18
        })

        exclude_games.Command().handle('de')
        self._assert_listed(self.de)
