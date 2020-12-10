import datetime

from unittest import mock

from django.core import mail
from django.test.utils import override_settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    addon_factory,
    TestCase,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import VERIFIED, NOT_PROMOTED
from olympia.promoted.models import PromotedAddon
from olympia.promoted.tasks import (
    on_stripe_charge_failed,
    on_stripe_charge_succeeded,
    on_stripe_customer_subscription_deleted,
)


class PromotedAddonTestCase(TestCase):
    EVENT_TYPE = 'invalid.event.type'

    def setUp(self):
        super().setUp()

        self.addon = addon_factory()
        self.promoted_addon = PromotedAddon.objects.create(
            addon=self.addon, group_id=VERIFIED.id
        )

    def create_stripe_event(self, event_id='some-id', **kwargs):
        return {
            'id': event_id,
            'type': self.EVENT_TYPE,
            **kwargs,
        }


class TestOnStripeChargeFailed(PromotedAddonTestCase):
    EVENT_TYPE = 'charge.failed'

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_ignores_invalid_event_type(self, retrieve_sub_mock):
        event = self.create_stripe_event(event_type='not-charge-failed')

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_ignores_events_without_data(self, retrieve_sub_mock):
        event = self.create_stripe_event(data={})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_ignores_events_without_data_object(self, retrieve_sub_mock):
        event = self.create_stripe_event(data={'object': None})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_ignores_unknown_promoted_subscriptions(self, retrieve_sub_mock):
        subscription_id = 'subscription-id'
        retrieve_sub_mock.return_value = {
            'id': subscription_id,
            'livemode': False,
        }
        invoice_id = 'invoice-id'
        fake_charge = {'id': 'charge-id', 'invoice': invoice_id}
        event = self.create_stripe_event(data={'object': fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 0

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_ignores_stripe_errors(self, retrieve_sub_mock):
        retrieve_sub_mock.side_effect = ValueError('stripe error')
        invoice_id = 'invoice-id'
        fake_charge = {'id': 'charge-id', 'invoice': invoice_id}
        event = self.create_stripe_event(data={'object': fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 0

    @override_settings(VERIFIED_ADDONS_EMAIL='verified@example.com')
    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_sends_email_to_amo_admins(self, retrieve_sub_mock):
        subscription_id = 'subscription-id'
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id
        )
        retrieve_sub_mock.return_value = {
            'id': subscription_id,
            'livemode': False,
        }
        invoice_id = 'invoice-id'
        fake_charge = {'id': 'charge-id', 'invoice': invoice_id}
        event = self.create_stripe_event(data={'object': fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert (
            email.subject
            == f'Stripe payment failure detected for add-on: {self.addon.name}'
        )
        assert email.to == ['verified@example.com']
        assert (
            f'following add-on: {absolutify(self.addon.get_detail_url())}' in email.body
        )
        assert (
            absolutify(
                reverse(
                    'admin:discovery_promotedaddon_change',
                    args=[self.promoted_addon.id],
                )
            )
            in email.body
        )
        assert (
            f'//dashboard.stripe.com/test/subscriptions/{subscription_id}' in email.body
        )

    @mock.patch('olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice')
    def test_sends_email_to_amo_admins_in_livemode(self, retrieve_sub_mock):
        subscription_id = 'subscription-id'
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id
        )
        retrieve_sub_mock.return_value = {
            'id': subscription_id,
            'livemode': True,
        }
        fake_charge = {'id': 'charge-id', 'invoice': 'invoice-id'}
        event = self.create_stripe_event(data={'object': fake_charge})

        on_stripe_charge_failed(event=event)

        assert (
            f'//dashboard.stripe.com/subscriptions/{subscription_id}'
            in mail.outbox[0].body
        )


class TestOnStripeCustomerSubscriptionDeleted(PromotedAddonTestCase):
    EVENT_TYPE = 'customer.subscription.deleted'

    def test_ignores_invalid_event_type(self):
        event = self.create_stripe_event(event_type='not-subscription-deleted')

        on_stripe_customer_subscription_deleted(event=event)

        assert not self.promoted_addon.promotedsubscription.cancelled_at

    def test_ignores_events_without_data(self):
        event = self.create_stripe_event(data={})

        on_stripe_customer_subscription_deleted(event=event)

        assert not self.promoted_addon.promotedsubscription.cancelled_at

    def test_ignores_events_without_data_object(self):
        event = self.create_stripe_event(data={'object': None})

        on_stripe_customer_subscription_deleted(event=event)

        assert not self.promoted_addon.promotedsubscription.cancelled_at

    def test_ignores_unknown_promoted_subscriptions(self):
        fake_subscription = {'id': 'unknown-sub-id'}
        event = self.create_stripe_event(data={'object': fake_subscription})

        on_stripe_customer_subscription_deleted(event=event)

        assert not self.promoted_addon.promotedsubscription.cancelled_at

    def test_ignores_already_cancelled_subscriptions(self):
        subscription_id = 'stripe-sub-id'
        cancelled_at = datetime.datetime(2020, 11, 1)
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id, cancelled_at=cancelled_at
        )
        fake_subscription = {'id': subscription_id}
        event = self.create_stripe_event(data={'object': fake_subscription})

        on_stripe_customer_subscription_deleted(event=event)

        assert self.promoted_addon.promotedsubscription.cancelled_at == cancelled_at

    def test_cancels_subscription(self):
        subscription_id = 'stripe-sub-id'
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id
        )
        cancelled_at = datetime.datetime.now()
        fake_subscription = {
            'id': subscription_id,
            'canceled_at': cancelled_at.timestamp(),
        }
        event = self.create_stripe_event(data={'object': fake_subscription})

        on_stripe_customer_subscription_deleted(event=event)
        self.promoted_addon.refresh_from_db()

        assert self.promoted_addon.promotedsubscription.cancelled_at == cancelled_at
        assert self.promoted_addon.group_id == NOT_PROMOTED.id


class TestOnStripeChargeSucceeded(PromotedAddonTestCase):
    EVENT_TYPE = 'charge.succeeded'

    def test_ignores_invalid_event_type(self):
        event = self.create_stripe_event(event_type='not-charge-succeeded')

        on_stripe_charge_succeeded(event=event)

        assert len(mail.outbox) == 0

    def test_ignores_events_without_data(self):
        event = self.create_stripe_event(data={})

        on_stripe_charge_succeeded(event=event)

        assert len(mail.outbox) == 0

    def test_ignores_events_without_data_object(self):
        event = self.create_stripe_event(data={'object': None})

        on_stripe_charge_succeeded(event=event)

        assert len(mail.outbox) == 0

    @override_settings(VERIFIED_ADDONS_EMAIL='verified@example.com')
    def test_sends_email(self):
        payment_intent = 'payment-intent'
        fake_charge = {
            'id': 'charge-id',
            'payment_intent': payment_intent,
        }
        event = self.create_stripe_event(data={'object': fake_charge})

        on_stripe_charge_succeeded(event=event)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.subject == 'Stripe payment succeeded'
        assert email.to == ['verified@example.com']
        assert f'//dashboard.stripe.com/test/payments/{payment_intent}' in email.body
