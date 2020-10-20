import datetime

from django.test.utils import override_settings

from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.urlresolvers import reverse
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

    def test_get_relative_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(
            promoted_addon=promoted_addon
        ).get()

        assert sub.get_onboarding_url(absolute=False) == reverse(
            "devhub.addons.onboarding_subscription",
            args=[sub.promoted_addon.addon.slug],
        )

    def test_get_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(
            promoted_addon=promoted_addon
        ).get()

        external_site_url = "http://example.org"
        with override_settings(EXTERNAL_SITE_URL=external_site_url):
            assert sub.get_onboarding_url() == "{}{}".format(
                external_site_url,
                reverse(
                    "devhub.addons.onboarding_subscription",
                    args=[sub.promoted_addon.addon.slug],
                ),
            )

    def test_stripe_checkout_completed(self):
        sub = PromotedSubscription()

        assert not sub.stripe_checkout_completed

        sub.update(payment_completed_at=datetime.datetime.now())

        assert sub.stripe_checkout_completed

    def test_stripe_checkout_cancelled(self):
        sub = PromotedSubscription()

        assert not sub.stripe_checkout_cancelled

        sub.update(payment_cancelled_at=datetime.datetime.now())

        assert sub.stripe_checkout_cancelled

    def test_addon_already_approved(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(
            promoted_addon=promoted_addon
        ).get()

        assert not sub.addon_already_promoted

        promoted_addon.approve_for_version(addon.current_version)
        sub.reload()

        assert sub.addon_already_promoted
