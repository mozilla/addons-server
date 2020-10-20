from olympia.amo.tests import addon_factory, TestCase
from olympia.constants import applications, promoted
from olympia.promoted.models import (
    PromotedAddon, PromotedApproval, PromotedSubscription)


class TestPromotedAddon(TestCase):

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id)
        assert promoted_addon.group == promoted.SPONSORED
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
        promoted_addon.update(group_id=promoted.SPONSORED.id)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version, group_id=promoted.SPONSORED.id,
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

    def test_creates_a_subscription_when_group_should_have_one(self):
        assert PromotedSubscription.objects.count() == 0

        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )

        assert PromotedSubscription.objects.count() == 1
        assert (PromotedSubscription.objects.all()[0].promoted_addon ==
                promoted_addon)

        # Do not create a subscription twice.
        promoted_addon.save()
        assert PromotedSubscription.objects.count() == 1

    def test_no_subscription_created_when_group_should_not_have_one(self):
        assert PromotedSubscription.objects.count() == 0

        PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.LINE.id
        )

        assert PromotedSubscription.objects.count() == 0


class TestPromotedSubscription(TestCase):
    def test_get_onboarding_url_with_new_object(self):
        sub = PromotedSubscription()

        assert sub.get_onboarding_url() is None

    def test_get_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(
            promoted_addon=promoted_addon
        ).get()

        assert 'onboarding' in sub.get_onboarding_url()
