from olympia.amo.tests import addon_factory, TestCase
from olympia.constants import applications, promoted
from olympia.promoted.models import PromotedAddon, PromotedApproval


class TestPromotedAddon(TestCase):

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.VERIFIED_ONE.id)
        assert promoted_addon.group == promoted.VERIFIED_ONE
        assert promoted_addon.application is None

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.application == applications.FIREFOX

    def test_is_addon_currently_promoted(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id)
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert not addon.promotedaddon.is_addon_currently_promoted

        # the current version needs to be approved also
        PromotedApproval.objects.create(
            version=addon.current_version, group_id=promoted.LINE.id)
        addon.reload()
        assert addon.promotedaddon.is_addon_currently_promoted

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.VERIFIED_ONE.id)
        assert not addon.promotedaddon.is_addon_currently_promoted
