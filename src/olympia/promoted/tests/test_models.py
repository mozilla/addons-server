import datetime
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.constants import applications, promoted
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
    PromotedSubscription,
)


class TestPromotedAddon(TestCase):
    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        assert promoted_addon.group == promoted.SPONSORED
        assert promoted_addon.application_id is None
        assert promoted_addon.all_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id
        )
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.SPONSORED.id)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=promoted.SPONSORED.id,
            application_id=applications.FIREFOX.id,
        )
        addon.reload()
        assert addon.promotedaddon.approved_applications == [applications.FIREFOX]

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=promoted.STRATEGIC.id)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

    def test_creates_a_subscription_when_group_should_have_one(self):
        assert PromotedSubscription.objects.count() == 0

        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )

        assert PromotedSubscription.objects.count() == 1
        assert PromotedSubscription.objects.all()[0].promoted_addon == promoted_addon

        # Do not create a subscription twice.
        promoted_addon.save()
        assert PromotedSubscription.objects.count() == 1

    def test_no_subscription_created_when_group_should_not_have_one(self):
        assert PromotedSubscription.objects.count() == 0

        PromotedAddon.objects.create(addon=addon_factory(), group_id=promoted.LINE.id)

        assert PromotedSubscription.objects.count() == 0

    def test_auto_approves_addon_when_saved_for_immediate_approval(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert promo.group == promoted.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.immediate_approval == False
        promo.group_id = promoted.RECOMMENDED.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        promo.addon.promoted_group() == promoted.NOT_PROMOTED

        # then with a group thats immediate_approval == True
        promo.group_id = promoted.SPOTLIGHT.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX]
        assert PromotedApproval.objects.count() == 1
        promo.addon.promoted_group() == promoted.SPOTLIGHT

        # test the edge case where the application was changed afterwards
        promo.application_id = 0
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX, amo.ANDROID]
        assert PromotedApproval.objects.count() == 2

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_approve_for_addon(self, mock_sign_file):
        core.set_user(user_factory())
        task_user = user_factory(id=settings.TASK_USER_ID)
        promo = PromotedAddon.objects.create(
            addon=addon_factory(version_kw={'version': '0.123a'}),
            group_id=promoted.SPOTLIGHT.id,
        )
        file_ = promo.addon.current_version.all_files[0]
        file_.update(filename='webextension.xpi')
        with amo.tests.copy_file(
            'src/olympia/files/fixtures/files/webextension.xpi', file_.file_path
        ):
            # SPOTLIGHT doesnt have special signing states so won't be resigned
            promo.addon.reload()
            promo.addon.promoted_group() == promoted.NOT_PROMOTED
            promo.approve_for_addon()
            promo.addon.reload()
            promo.addon.promoted_group() == promoted.SPOTLIGHT
            assert promo.addon.current_version.version == '0.123a'
            mock_sign_file.assert_not_called()

            # VERIFIED does though.
            promo.update(group_id=promoted.VERIFIED.id)
            promo.addon.reload()
            promo.addon.promoted_group() == promoted.NOT_PROMOTED
            promo.approve_for_addon()
            promo.addon.reload()
            promo.addon.promoted_group() == promoted.VERIFIED
            assert promo.addon.current_version.version == '0.123a.1-signed'
            mock_sign_file.assert_called_with(file_)
            assert (
                ActivityLog.objects.for_addons((promo.addon,))
                .filter(action=amo.LOG.VERSION_RESIGNED.id)
                .exists()
            )
            alog = ActivityLog.objects.filter(action=amo.LOG.VERSION_RESIGNED.id).get()
            assert alog.user == task_user
            assert '0.123a.1-signed</a> re-signed (previously 0.123a)' in (str(alog))

    def test_get_resigned_version_number(self):
        addon = addon_factory(
            version_kw={'version': '0.123a'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        promo = PromotedAddon.objects.create(addon=addon, group_id=promoted.VERIFIED.id)
        assert addon.current_version is not None
        assert promo.get_resigned_version_number() is None

        addon.current_version.current_file.update(status=amo.STATUS_APPROVED)
        assert promo.get_resigned_version_number() == '0.123a.1-signed'

        addon.current_version.update(version='123.4.1-signed')
        assert promo.get_resigned_version_number() == '123.4.1-signed-2'

        addon.current_version.update(version='123.4.1-signed-2')
        assert promo.get_resigned_version_number() == '123.4.1-signed-3'

        addon.current_version.delete()
        addon.reload()
        assert addon.current_version is None
        assert promo.get_resigned_version_number() is None

    def test_has_pending_subscription(self):
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.RECOMMENDED.id
        )
        PromotedSubscription.objects.create(promoted_addon=promo)

        # checking the group doesn't require subscription
        assert not promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert not promo.promotedsubscription.is_active
        assert not promo.has_approvals
        assert not promo.has_pending_subscription

        # and when it does
        promo.update(group_id=promoted.VERIFIED.id)
        assert promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert not promo.promotedsubscription.is_active
        assert not promo.has_approvals
        assert promo.has_pending_subscription

        # when there isn't a subscription (existing promo before subscriptions)
        promo.promotedsubscription.delete()
        promo = PromotedAddon.objects.get(id=promo.id)
        assert promo.group.require_subscription
        assert not hasattr(promo, 'promotedsubscription')
        assert not promo.has_pending_subscription

        # and when there is
        PromotedSubscription.objects.create(promoted_addon=promo)
        assert promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert not promo.promotedsubscription.is_active
        assert not promo.has_approvals
        assert promo.has_pending_subscription

        # when there's a subscription that's been paid
        promo.promotedsubscription.update(checkout_completed_at=datetime.datetime.now())
        assert promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert promo.promotedsubscription.is_active
        assert not promo.has_approvals
        assert not promo.has_pending_subscription

        # and when it's not been paid
        promo.promotedsubscription.update(checkout_completed_at=None)
        assert promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert not promo.promotedsubscription.is_active
        assert not promo.has_approvals
        assert promo.has_pending_subscription

        # when there's an existing version approved (existing promo)
        promo.approve_for_version(promo.addon.current_version)
        assert promo.group.require_subscription
        assert hasattr(promo, 'promotedsubscription')
        assert not promo.promotedsubscription.is_active
        assert promo.has_approvals
        assert not promo.has_pending_subscription

    def test_has_approvals(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.SPONSORED.id
        )

        assert not promoted_addon.has_approvals

        promoted_addon.approve_for_version(addon.current_version)
        promoted_addon.reload()

        assert promoted_addon.has_approvals


class TestPromotedSubscription(TestCase):
    def test_get_onboarding_url_with_new_object(self):
        sub = PromotedSubscription()

        assert sub.get_onboarding_url() is None

    def test_get_relative_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()

        assert sub.get_onboarding_url(absolute=False) == reverse(
            'devhub.addons.onboarding_subscription',
            args=[sub.promoted_addon.addon.slug],
            add_prefix=False,
        )

    def test_get_onboarding_url(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()

        external_site_url = 'http://example.org'
        with override_settings(EXTERNAL_SITE_URL=external_site_url):
            url = sub.get_onboarding_url()
            assert url == '{}{}'.format(
                external_site_url,
                reverse(
                    'devhub.addons.onboarding_subscription',
                    args=[sub.promoted_addon.addon.slug],
                    add_prefix=False,
                ),
            )
            assert 'en-US' not in url

    def test_stripe_checkout_completed(self):
        sub = PromotedSubscription()

        assert not sub.stripe_checkout_completed

        sub.update(checkout_completed_at=datetime.datetime.now())

        assert sub.stripe_checkout_completed

    def test_stripe_checkout_cancelled(self):
        sub = PromotedSubscription()

        assert not sub.stripe_checkout_cancelled

        sub.update(checkout_cancelled_at=datetime.datetime.now())

        assert sub.stripe_checkout_cancelled

    def test_is_active(self):
        sub = PromotedSubscription()

        assert sub.is_active is None

        sub.update(checkout_completed_at=datetime.datetime.now())

        assert sub.is_active

        sub.update(cancelled_at=datetime.datetime.now())

        assert sub.is_active is False
