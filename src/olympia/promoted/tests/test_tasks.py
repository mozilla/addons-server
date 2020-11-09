from unittest import mock

from django.core import mail

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    addon_factory,
    TestCase,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import VERIFIED
from olympia.promoted.models import PromotedAddon
from olympia.promoted.tasks import on_stripe_charge_failed


class TestOnStripeChargeFailed(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory()
        self.promoted_addon = PromotedAddon.objects.create(
            addon=self.addon, group_id=VERIFIED.id
        )

    def create_stripe_event(
        self, event_id="some-id", event_type="charge.failed", **kwargs
    ):
        return {
            "id": event_id,
            "type": event_type,
            **kwargs,
        }

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_ignores_invalid_event_type(self, retrieve_sub_mock):
        event = self.create_stripe_event(event_type="not-charge-failed")

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_ignores_events_without_data(self, retrieve_sub_mock):
        event = self.create_stripe_event(data={})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_ignores_events_without_data_object(self, retrieve_sub_mock):
        event = self.create_stripe_event(data={"object": None})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_not_called()

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_ignores_unknown_promoted_subscriptions(self, retrieve_sub_mock):
        subscription_id = "subscription-id"
        retrieve_sub_mock.return_value = {
            "id": subscription_id,
            "livemode": False,
        }
        invoice_id = "invoice-id"
        fake_charge = {"id": "charge-id", "invoice": invoice_id}
        event = self.create_stripe_event(data={"object": fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 0

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_ignores_stripe_errors(self, retrieve_sub_mock):
        retrieve_sub_mock.side_effect = ValueError("stripe error")
        invoice_id = "invoice-id"
        fake_charge = {"id": "charge-id", "invoice": invoice_id}
        event = self.create_stripe_event(data={"object": fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 0

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_sends_email_to_amo_admins(self, retrieve_sub_mock):
        subscription_id = "subscription-id"
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id
        )
        retrieve_sub_mock.return_value = {
            "id": subscription_id,
            "livemode": False,
        }
        invoice_id = "invoice-id"
        fake_charge = {"id": "charge-id", "invoice": invoice_id}
        event = self.create_stripe_event(data={"object": fake_charge})

        on_stripe_charge_failed(event=event)

        retrieve_sub_mock.assert_called_once_with(invoice_id=invoice_id)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert (
            email.subject ==
            f"Stripe payment failure detected for add-on: {self.addon.name}"
        )
        assert email.to == ["amo-admins@mozilla.com"]
        assert (
            f"following add-on: {absolutify(self.addon.get_detail_url())}"
            in email.body
        )
        assert (
            absolutify(
                reverse(
                    "admin:discovery_promotedaddon_change",
                    args=[self.promoted_addon.id],
                )
            )
            in email.body
        )
        assert (
            f"//dashboard.stripe.com/test/subscriptions/{subscription_id}"
            in email.body
        )

    @mock.patch(
        "olympia.promoted.tasks.retrieve_stripe_subscription_for_invoice"
    )
    def test_sends_email_to_amo_admins_in_livemode(self, retrieve_sub_mock):
        subscription_id = "subscription-id"
        self.promoted_addon.promotedsubscription.update(
            stripe_subscription_id=subscription_id
        )
        retrieve_sub_mock.return_value = {
            "id": subscription_id,
            "livemode": True,
        }
        fake_charge = {"id": "charge-id", "invoice": "invoice-id"}
        event = self.create_stripe_event(data={"object": fake_charge})

        on_stripe_charge_failed(event=event)

        assert (
            f"//dashboard.stripe.com/subscriptions/{subscription_id}"
            in mail.outbox[0].body
        )
