from olympia.amo.tests import TestCase, addon_factory
from olympia.hero.models import PrimaryHero
from olympia.hero.tasks import sync_primary_hero_addon
from olympia.promoted.models import PromotedAddon


class TestSyncPrimaryHeroAddon(TestCase):
    def test_no_heros(self):
        assert PrimaryHero.objects.count() == 0
        sync_primary_hero_addon.apply()
        assert PrimaryHero.objects.count() == 0

    def test_with_legacy_promoted_addon(self):
        addon = addon_factory()
        # Create legacy promoted_addon
        promoted_addon = PromotedAddon.objects.create(addon=addon)
        # Also make the addon promoted with the new promoted addon model
        self.make_addon_promoted(addon, 1)
        hero = PrimaryHero.objects.create(promoted_addon=promoted_addon)
        sync_primary_hero_addon.apply()
        hero.reload()
        assert hero.addon == addon

    def test_with_new_promoted_addon(self):
        addon = addon_factory()
        self.make_addon_promoted(addon, 1)
        hero = PrimaryHero.objects.create(addon=addon)
        sync_primary_hero_addon.apply()
        hero.reload()
        assert hero.addon == addon

    def test_with_no_addon_or_legacy_promoted_addon_should_raise(self):
        """
        During the transition to using `addon` instead of `promoted_addon`,
        It is possible that there are some heroes that have neither an addon
        or a promoted addon. This should not happen, but we should handle the edge case
        until we have removed the legacy promoted_addon field.
        """
        PrimaryHero.objects.create()

        with self.assertLogs(logger='z.hero', level='ERROR') as cm:
            sync_primary_hero_addon.apply()

        assert 'Invalid PrimaryHero records' in cm.output[0]
