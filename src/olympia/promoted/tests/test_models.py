from olympia.amo.tests import addon_factory, TestCase
from olympia.constants import promoted
from olympia.promoted.models import PromotedAddon, PromotedApproval


class TestPromotedAddon(TestCase):

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.VERIFIED_ONE.id)
        assert promoted_addon.group == promoted.VERIFIED_ONE
        assert (
            str(promoted_addon.name) == str(promoted.VERIFIED_ONE.name) ==
            'Verified - Tier 1')

    def test_is_addon_promoted(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id)
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert not addon.promotedaddon.is_addon_promoted()

        # the current version needs to be approved also
        PromotedApproval.objects.create(
            version=addon.current_version, group_id=promoted.LINE.id)
        assert addon.promotedaddon.is_addon_promoted()

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.VERIFIED_ONE.id)
        assert not addon.promotedaddon.is_addon_promoted()
