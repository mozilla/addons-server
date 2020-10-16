from olympia.amo.tests import addon_factory, TestCase
from olympia.constants import applications, promoted
from olympia.promoted.models import (
    PromotedAddon, PromotedApproval, PromotedSubscription)


class TestPromotedAddon(TestCase):

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.VERIFIED_ONE.id)
        assert promoted_addon.group == promoted.VERIFIED_ONE
        assert promoted_addon.application_id is None
        assert promoted_addon.all_applications == [
            applications.FIREFOX, applications.ANDROID]

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id)
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX, applications.ANDROID]

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.VERIFIED_ONE.id)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version, group_id=promoted.VERIFIED_ONE.id,
            application_id=applications.FIREFOX.id)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX]

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=promoted.STRATEGIC.id)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX, applications.ANDROID]


class TestPromotedSubscription(TestCase):
    def test_get_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.VERIFIED_ONE.id
        )
        sub = PromotedSubscription(promoted_addon=promoted_addon)

        assert sub.get_onboarding_url() is None

        sub.save()

        assert 'onboarding' in sub.get_onboarding_url()
