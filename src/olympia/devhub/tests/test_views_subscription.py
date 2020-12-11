import datetime

from unittest import mock
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import VERIFIED
from olympia.promoted.models import PromotedAddon, PromotedSubscription


@override_switch('enable-subscriptions-for-promoted-addons', active=True)
class SubscriptionTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.dev_user = user_factory()
        self.addon = addon_factory(users=[self.user])
        self.addon.addonuser_set.create(user=self.dev_user, role=amo.AUTHOR_ROLE_DEV)
        self.promoted_addon = PromotedAddon.objects.create(
            addon=self.addon, group_id=VERIFIED.id
        )
        self.subscription = PromotedSubscription.objects.filter(
            promoted_addon=self.promoted_addon
        ).get()
        self.url = reverse(self.url_name, args=[self.addon.slug])
        self.client.login(email=self.user.email)


class TestOnboardingSubscription(SubscriptionTestCase):
    url_name = 'devhub.addons.onboarding_subscription'

    @override_switch('enable-subscriptions-for-promoted-addons', active=False)
    def test_returns_404_when_switch_is_disabled(self):
        assert self.client.get(self.url).status_code == 404

    def test_returns_404_when_subscription_is_not_found(self):
        # Create an add-on without a subscription.
        addon = addon_factory(users=[self.user])
        url = reverse(self.url_name, args=[addon.slug])
        assert self.client.get(url).status_code == 404

    def test_returns_403_for_non_owners(self):
        self.client.logout()
        self.client.login(email=self.dev_user.email)

        response = self.client.get(self.url)

        assert response.status_code == 403

    def test_returns_404_when_subscription_has_been_cancelled(self):
        self.subscription.update(
            checkout_completed_at=datetime.datetime.now(),
            cancelled_at=datetime.datetime.now(),
        )

        response = self.client.get(self.url)

        assert response.status_code == 404

    @mock.patch('olympia.devhub.views.create_stripe_checkout_session')
    def test_get_for_the_first_time(self, create_mock):
        create_mock.return_value = dict(id='session-id')

        assert not self.subscription.link_visited_at
        assert not self.subscription.stripe_session_id

        response = self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert response.status_code == 200
        create_mock.assert_called_with(
            self.subscription, customer_email=self.user.email
        )
        assert self.subscription.link_visited_at is not None
        assert self.subscription.stripe_session_id == 'session-id'
        assert (
            response.context['stripe_session_id'] == self.subscription.stripe_session_id
        )
        assert response.context['addon'] == self.addon
        assert not response.context['stripe_checkout_completed']
        assert not response.context['stripe_checkout_cancelled']
        assert response.context['promoted_group'] == self.promoted_addon.group
        assert (
            b'Thank you for joining the Promoted Add-ons Program!' in response.content
        )

    @mock.patch('olympia.devhub.views.create_stripe_checkout_session')
    def test_get(self, create_mock):
        create_mock.side_effect = [
            dict(id='session-id-1'),
            dict(id='session-id-2'),
        ]

        # Get the page.
        queries = 36
        with self.assertNumQueries(queries):
            # - 3 users + groups
            # - 2 savepoints (test)
            # - 3 addon and its translations
            # - 2 addon categories
            # - 4 versions and translations
            # - 2 application versions
            # - 2 files
            # - 5 addon users
            # - 2 previews
            # - 1 waffle switch
            # - 1 promoted subscription
            # - 1 promoted add-on
            # - 1 UPDATE promoted subscription
            # - 1 addons_collections
            # - 1 config (site notice)
            response = self.client.get(self.url)
        self.subscription.refresh_from_db()

        link_visited_at = self.subscription.link_visited_at
        assert link_visited_at
        assert self.subscription.stripe_session_id == 'session-id-1'

        # Get the page, again.
        with self.assertNumQueries(queries - 1):
            # - waffle switch is cached
            response = self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert response.status_code == 200
        assert self.subscription.link_visited_at == link_visited_at
        assert self.subscription.stripe_session_id == 'session-id-2'

    @mock.patch('olympia.devhub.views.create_stripe_checkout_session')
    def test_shows_page_with_admin(self, create_mock):
        admin = user_factory()
        self.grant_permission(admin, '*:*')
        self.client.logout()
        self.client.login(email=admin.email)
        create_mock.return_value = dict(id='session-id')

        assert not self.subscription.link_visited_at

        response = self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert response.status_code == 200
        # We don't set this date when the user is not the owner (in this case,
        # the user is an admin).
        assert not self.subscription.link_visited_at

    @mock.patch('olympia.devhub.views.create_stripe_checkout_session')
    def test_shows_error_message_when_payment_was_previously_cancelled(
        self, create_mock
    ):
        create_mock.return_value = dict(id='session-id')
        self.subscription.update(checkout_cancelled_at=datetime.datetime.now())

        response = self.client.get(self.url)

        assert (
            b'There was an error while setting up payment for your add-on.'
            in response.content
        )
        assert b'Continue to Stripe Checkout' in response.content
        assert b'Manage add-on' not in response.content
        create_mock.assert_called_with(
            self.subscription, customer_email=self.user.email
        )

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_shows_confirmation_after_payment(self, retrieve_mock):
        # With an approved version but nothing in the session this is testing
        # a subscription where the addon was already approved for promotion.
        self.promoted_addon.approve_for_version(self.addon.current_version)
        stripe_session_id = 'some session id'
        retrieve_mock.return_value = dict(id=stripe_session_id)
        self.subscription.update(
            stripe_session_id=stripe_session_id,
            checkout_completed_at=datetime.datetime.now(),
        )

        response = self.client.get(self.url)

        assert b"You're done!" in response.content
        assert b'Continue to Stripe Checkout' not in response.content
        assert b'Manage add-on' in response.content
        retrieve_mock.assert_called_with(self.subscription)

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_shows_request_to_upload_after_payment(self, retrieve_mock):
        # If there isn't an approved version the developer needs to upload one.
        stripe_session_id = 'some session id'
        retrieve_mock.return_value = dict(id=stripe_session_id)
        self.subscription.update(
            stripe_session_id=stripe_session_id,
            checkout_completed_at=datetime.datetime.now(),
        )

        response = self.client.get(self.url)

        assert b"You're done!" not in response.content
        assert b'Please upload a new public version' in response.content
        assert b'Continue to Stripe Checkout' not in response.content
        assert b'Manage add-on' in response.content
        retrieve_mock.assert_called_with(self.subscription)

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_returns_500_when_retrieve_has_failed(self, retrieve_mock):
        stripe_session_id = 'some session id'
        self.subscription.update(
            stripe_session_id=stripe_session_id,
            checkout_completed_at=datetime.datetime.now(),
        )
        retrieve_mock.side_effect = Exception('stripe error')

        response = self.client.get(self.url)

        assert response.status_code == 500

    @mock.patch('olympia.devhub.views.create_stripe_checkout_session')
    def test_get_returns_500_when_create_has_failed(self, create_mock):
        create_mock.side_effect = Exception('stripe error')

        response = self.client.get(self.url)

        assert response.status_code == 500

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_shows_confirmation_after_payment_already_approved(self, retrieve_mock):
        stripe_session_id = 'session id'
        retrieve_mock.return_value = dict(id=stripe_session_id)
        self.subscription.update(
            stripe_session_id=stripe_session_id,
            checkout_completed_at=datetime.datetime.now(),
        )
        self.promoted_addon.approve_for_version(self.addon.current_version)

        response = self.client.get(self.url)

        assert b"You're done!" in response.content
        retrieve_mock.assert_called_with(self.subscription)


class TestOnboardingSubscriptionSuccess(SubscriptionTestCase):
    url_name = 'devhub.addons.onboarding_subscription_success'

    @override_switch('enable-subscriptions-for-promoted-addons', active=False)
    def test_returns_404_when_switch_is_disabled(self):
        assert self.client.get(self.url).status_code == 404

    def test_returns_404_when_subscription_is_not_found(self):
        # Create an add-on without a subscription.
        addon = addon_factory(users=[self.user])
        url = reverse(self.url_name, args=[addon.slug])
        assert self.client.get(url).status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_returns_404_when_session_not_found(self, retrieve_mock):
        retrieve_mock.side_effect = Exception('stripe error')

        response = self.client.get(self.url)

        assert response.status_code == 404

    def test_returns_403_for_non_owners(self):
        self.client.logout()
        self.client.login(email=self.dev_user.email)

        response = self.client.get(self.url)

        assert response.status_code == 403

    def test_returns_404_when_subscription_has_been_cancelled(self):
        self.subscription.update(
            checkout_completed_at=datetime.datetime.now(),
            cancelled_at=datetime.datetime.now(),
        )

        response = self.client.get(self.url)

        assert response.status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_redirects_to_main_page(self, retrieve_mock):
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'unpaid',
            'subscription': None,
        }

        response = self.client.get(self.url)

        assert response.status_code == 302
        assert response['Location'].endswith('/onboarding-subscription')

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_records_payment_once(self, retrieve_mock):
        self.subscription.promoted_addon.approve_for_version(
            self.subscription.promoted_addon.addon.current_version
        )
        stripe_subscription_id = 'some-subscription-id'
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'paid',
            'subscription': stripe_subscription_id,
        }

        assert not self.subscription.checkout_completed_at

        self.client.get(self.url)
        self.subscription.refresh_from_db()

        checkout_completed_at = self.subscription.checkout_completed_at
        assert checkout_completed_at is not None
        assert self.subscription.stripe_subscription_id == stripe_subscription_id

        self.client.get(self.url)
        self.subscription.refresh_from_db()

        # Make sure we don't update this date again.
        assert self.subscription.checkout_completed_at == checkout_completed_at
        assert not self.subscription.checkout_cancelled_at
        assert self.subscription.stripe_subscription_id == stripe_subscription_id

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_resets_payment_cancelled_date_after_success(self, retrieve_mock):
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'paid',
            'subscription': 'some-subscription-id',
        }
        self.subscription.promoted_addon.approve_for_version(
            self.subscription.promoted_addon.addon.current_version
        )

        self.subscription.update(checkout_cancelled_at=datetime.datetime.now())

        self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert not self.subscription.checkout_cancelled_at

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_current_version_is_approved_after_success(self, retrieve_mock):
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'paid',
            'subscription': 'some-subscription-id',
        }

        self.subscription.promoted_addon.addon.current_version.update(version='123')
        assert not self.subscription.promoted_addon.addon.promoted_group()
        with mock.patch('olympia.lib.crypto.tasks.sign_addons') as sign_mock:
            response = self.client.get(self.url, follow=True)
            sign_mock.assert_called()
        self.subscription.refresh_from_db()
        assert self.subscription.promoted_addon.addon.promoted_group() == VERIFIED
        assert b'123.1-signed' in response.content
        assert b'currently pending review' not in response.content

        # the message is gone the second time
        response = self.client.get(
            reverse(TestOnboardingSubscription.url_name, args=[self.addon.slug]),
            follow=True,
        )
        assert b"You're done" in response.content
        assert b'123.1-signed' not in response.content

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_current_version_is_approved_pending_version(self, retrieve_mock):
        """Same as test_current_version_is_approved_after_success but when
        there is a pending version too."""
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'paid',
            'subscription': 'some-subscription-id',
        }

        self.subscription.promoted_addon.addon.current_version.update(version='123')
        # add a pending version we'll highlight too
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )

        assert not self.subscription.promoted_addon.addon.promoted_group()
        with mock.patch('olympia.lib.crypto.tasks.sign_addons') as sign_mock:
            response = self.client.get(self.url, follow=True)
            sign_mock.assert_called()
        self.subscription.refresh_from_db()
        assert self.subscription.promoted_addon.addon.promoted_group() == VERIFIED
        assert b'123.1-signed' in response.content
        assert b'currently pending review' in response.content

        # the message is gone the second time
        response = self.client.get(
            reverse(TestOnboardingSubscription.url_name, args=[self.addon.slug]),
            follow=True,
        )
        assert b"You're done" in response.content
        assert b'123.1-signed' not in response.content

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_version_isnt_resigned_if_already_approved(self, retrieve_mock):
        retrieve_mock.return_value = {
            'id': 'session-id',
            'payment_status': 'paid',
            'subscription': 'some-subscription-id',
        }

        promo = self.subscription.promoted_addon
        promo.approve_for_version(promo.addon.current_version)
        assert promo.addon.promoted_group() == VERIFIED  # approved already
        with mock.patch('olympia.lib.crypto.tasks.sign_addons') as sign_mock:
            self.client.get(self.url)
            sign_mock.assert_not_called()  # no resigning needed
        self.subscription.refresh_from_db()
        assert self.subscription.checkout_completed_at
        assert promo.addon.promoted_group() == VERIFIED  # still approved


class TestOnboardingSubscriptionCancel(SubscriptionTestCase):
    url_name = 'devhub.addons.onboarding_subscription_cancel'

    @override_switch('enable-subscriptions-for-promoted-addons', active=False)
    def test_returns_404_when_switch_is_disabled(self):
        assert self.client.get(self.url).status_code == 404

    def test_returns_404_when_subscription_is_not_found(self):
        # Create an add-on without a subscription.
        addon = addon_factory(users=[self.user])
        url = reverse(self.url_name, args=[addon.slug])
        assert self.client.get(url).status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_returns_404_when_session_not_found(self, retrieve_mock):
        retrieve_mock.side_effect = Exception('stripe error')

        response = self.client.get(self.url)

        assert response.status_code == 404

    def test_returns_403_for_non_owners(self):
        self.client.logout()
        self.client.login(email=self.dev_user.email)

        response = self.client.get(self.url)

        assert response.status_code == 403

    def test_returns_404_when_subscription_has_been_cancelled(self):
        self.subscription.update(
            checkout_completed_at=datetime.datetime.now(),
            cancelled_at=datetime.datetime.now(),
        )

        response = self.client.get(self.url)

        assert response.status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_redirects_to_main_page(self, retrieve_mock):
        retrieve_mock.return_value = dict(id='session-id')

        response = self.client.get(self.url)

        assert response.status_code == 302
        assert response['Location'].endswith('/onboarding-subscription')

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_sets_payment_cancelled_date(self, retrieve_mock):
        stripe_session_id = 'some session id'
        self.subscription.update(stripe_session_id=stripe_session_id)
        retrieve_mock.return_value = dict(id=stripe_session_id)

        assert not self.subscription.checkout_cancelled_at

        self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert self.subscription.checkout_cancelled_at

    @mock.patch('olympia.devhub.views.retrieve_stripe_checkout_session')
    def test_get_does_not_set_payment_cancelled_date_when_already_paid(
        self, retrieve_mock
    ):
        retrieve_mock.return_value = dict(id='session-id')

        self.subscription.update(checkout_completed_at=datetime.datetime.now())
        assert not self.subscription.checkout_cancelled_at

        self.client.get(self.url)
        self.subscription.refresh_from_db()

        assert not self.subscription.checkout_cancelled_at


@override_switch('enable-subscriptions-for-promoted-addons', active=True)
class TestSubscriptionCustomerPortal(SubscriptionTestCase):
    url_name = 'devhub.addons.subscription_customer_portal'

    @override_switch('enable-subscriptions-for-promoted-addons', active=False)
    def test_returns_404_when_switch_is_disabled(self):
        assert self.client.post(self.url).status_code == 404

    def test_rejects_get_requests(self):
        assert self.client.get(self.url).status_code == 405

    def test_returns_404_when_subscription_is_not_found(self):
        # Create an add-on without a subscription.
        addon = addon_factory(users=[self.user])
        url = reverse(self.url_name, args=[addon.slug])

        assert self.client.post(url).status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_subscription')
    def test_get_returns_404_when_subscription_not_found(self, retrieve_mock):
        retrieve_mock.side_effect = Exception('stripe error')

        response = self.client.post(self.url)

        assert response.status_code == 404

    def test_returns_403_for_non_owners(self):
        self.client.logout()
        self.client.login(email=self.dev_user.email)

        response = self.client.post(self.url)

        assert response.status_code == 403

    def test_returns_404_when_subscription_has_been_cancelled(self):
        self.subscription.update(
            checkout_completed_at=datetime.datetime.now(),
            cancelled_at=datetime.datetime.now(),
        )

        response = self.client.post(self.url)

        assert response.status_code == 404

    @mock.patch('olympia.devhub.views.retrieve_stripe_subscription')
    @mock.patch('olympia.devhub.views.create_stripe_customer_portal')
    def test_redirects_to_stripe_customer_portal(self, create_mock, retrieve_mock):
        customer_id = 'some-customer-id'
        portal_url = 'https://stripe-portal.example.org'
        retrieve_mock.return_value = {'customer': customer_id}
        create_mock.return_value = {'url': portal_url}

        response = self.client.post(self.url)

        assert response.status_code == 302
        assert response['Location'] == portal_url
        retrieve_mock.assert_called_once_with(self.subscription)
        create_mock.assert_called_once_with(customer_id=customer_id, addon=self.addon)

    @mock.patch('olympia.devhub.views.retrieve_stripe_subscription')
    @mock.patch('olympia.devhub.views.create_stripe_customer_portal')
    def test_get_returns_500_when_create_has_failed(self, create_mock, retrieve_mock):
        retrieve_mock.return_value = {'customer': 'customer-id'}
        create_mock.side_effect = Exception('stripe error')

        response = self.client.post(self.url)

        assert response.status_code == 500
