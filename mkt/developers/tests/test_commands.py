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


class TestExcludeUnratedGames(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)

    def _germany_listed(self):
        return not self.webapp.geodata.region_de_iarc_exclude

    def _brazil_listed(self):
        return not self.webapp.geodata.region_br_iarc_exclude

    def test_exclude_unrated(self):
        amo.tests.make_game(self.webapp, rated=False)

        exclude_games.Command().handle()
        assert not self._brazil_listed()
        assert not self._germany_listed()

    def test_dont_exclude_non_game(self):
        exclude_games.Command().handle()
        assert self._brazil_listed()
        assert self._germany_listed()

    def test_dont_exclude_rated(self):
        amo.tests.make_game(self.webapp, rated=True)

        exclude_games.Command().handle()
        assert self._brazil_listed()
        assert self._germany_listed()

    def test_germany_case_generic(self):
        amo.tests.make_game(self.webapp, rated=False)
        self.webapp.set_content_ratings({
            mkt.ratingsbodies.GENERIC: mkt.ratingsbodies.GENERIC_18
        })

        exclude_games.Command().handle()
        assert self._germany_listed()
        assert not self._brazil_listed()

    def test_germany_case_usk(self):
        amo.tests.make_game(self.webapp, rated=False)
        self.webapp.set_content_ratings({
            mkt.ratingsbodies.USK: mkt.ratingsbodies.USK_18
        })

        exclude_games.Command().handle()
        assert self._germany_listed()
        assert not self._brazil_listed()

    def test_brazil_case_classind(self):
        amo.tests.make_game(self.webapp, rated=False)
        self.webapp.set_content_ratings({
            mkt.ratingsbodies.CLASSIND: mkt.ratingsbodies.CLASSIND_L
        })

        exclude_games.Command().handle()
        assert self._brazil_listed()
        assert not self._germany_listed()
