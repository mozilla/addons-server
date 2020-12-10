import pytest

from unittest import mock

from django.test.utils import override_settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import (
    BILLING_PERIOD_MONTHLY,
    BILLING_PERIOD_YEARLY,
    RECOMMENDED,
    SPONSORED,
    VERIFIED,
)
from olympia.promoted.models import PromotedSubscription, PromotedAddon
from olympia.promoted.utils import (
    create_stripe_checkout_session,
    create_stripe_customer_portal,
    create_stripe_webhook_event,
    retrieve_stripe_checkout_session,
    retrieve_stripe_subscription,
    retrieve_stripe_subscription_for_invoice,
)


def test_retrieve_stripe_checkout_session():
    stripe_session_id = 'some stripe session id'
    sub = PromotedSubscription(stripe_session_id=stripe_session_id)

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.retrieve'
    ) as stripe_retrieve:
        retrieve_stripe_checkout_session(subscription=sub)

        stripe_retrieve.assert_called_once_with(stripe_session_id)


@override_settings(STRIPE_API_SPONSORED_YEARLY_PRICE_ID='yearly-sponsored-price-id')
def test_create_stripe_checkout_session_for_sponsored():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=SPONSORED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create:
        stripe_create.return_value = fake_session
        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[{'price': 'yearly-sponsored-price-id', 'quantity': 1}],
            customer_email=customer_email,
        )


@override_settings(STRIPE_API_VERIFIED_MONTHLY_PRICE_ID='monthly-verified-price-id')
def test_create_stripe_checkout_session_for_verified():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=VERIFIED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create:
        stripe_create.return_value = fake_session
        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[{'price': 'monthly-verified-price-id', 'quantity': 1}],
            customer_email=customer_email,
        )


def test_create_stripe_checkout_session_with_invalid_group_id():
    promoted_addon = PromotedAddon.objects.create(
        addon=addon_factory(), group_id=RECOMMENDED.id
    )
    # We create the promoted subscription because the promoted add-on above
    # (recommended) does not create it automatically. This is because
    # recommended add-ons should not have a subscription.
    sub = PromotedSubscription.objects.create(promoted_addon=promoted_addon)

    with pytest.raises(ValueError):
        create_stripe_checkout_session(
            subscription=sub, customer_email='doesnotmatter@example.org'
        )


@override_settings(STRIPE_API_SPONSORED_YEARLY_PRICE_ID='yearly-sponsored-price-id')
def test_create_stripe_checkout_session_with_custom_rate():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=SPONSORED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    # Set a custom onboarding rate, in cents.
    onboarding_rate = 1234
    sub.update(onboarding_rate=onboarding_rate)
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'
    fake_product = {
        'product': 'some-product-id',
        'currency': 'some-currency',
        'recurring': {'interval': 'year', 'interval_count': 1},
    }

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create, mock.patch(
        'olympia.promoted.utils.stripe.Price.retrieve'
    ) as stripe_retrieve:
        stripe_create.return_value = fake_session
        stripe_retrieve.return_value = fake_product

        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[
                {
                    'price_data': {
                        'product': fake_product['product'],
                        'currency': fake_product['currency'],
                        'recurring': {
                            'interval': fake_product['recurring']['interval'],
                            'interval_count': fake_product['recurring'][
                                'interval_count'
                            ],
                        },
                        'unit_amount': onboarding_rate,
                    },
                    'quantity': 1,
                }
            ],
            customer_email=customer_email,
        )


@override_settings(STRIPE_API_SPONSORED_YEARLY_PRICE_ID='yearly-sponsored-price-id')
@override_settings(STRIPE_API_SPONSORED_MONTHLY_PRICE_ID='monthly-sponsored-price-id')
def test_create_stripe_checkout_session_for_sponsored_with_custom_period():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=SPONSORED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    # Set a custom billing period.
    sub.update(onboarding_period=BILLING_PERIOD_MONTHLY)
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create:
        stripe_create.return_value = fake_session

        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[{'price': 'monthly-sponsored-price-id', 'quantity': 1}],
            customer_email=customer_email,
        )


@override_settings(STRIPE_API_VERIFIED_YEARLY_PRICE_ID='yearly-verified-price-id')
@override_settings(STRIPE_API_VERIFIED_MONTHLY_PRICE_ID='monthly-verified-price-id')
def test_create_stripe_checkout_session_for_verified_with_custom_period():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=VERIFIED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    # Set a custom billing period.
    sub.update(onboarding_period=BILLING_PERIOD_YEARLY)
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create:
        stripe_create.return_value = fake_session

        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[{'price': 'yearly-verified-price-id', 'quantity': 1}],
            customer_email=customer_email,
        )


@override_settings(STRIPE_API_SPONSORED_MONTHLY_PRICE_ID='monthlty-sponsored-price-id')
def test_create_stripe_checkout_session_with_custom_rate_and_period():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(addon=addon, group_id=SPONSORED.id)
    sub = PromotedSubscription.objects.filter(promoted_addon=promoted_addon).get()
    # Set a custom onboarding rate (in cents) and a custom onboarding period.
    onboarding_rate = 1234
    sub.update(
        onboarding_rate=onboarding_rate,
        onboarding_period=BILLING_PERIOD_MONTHLY,
    )
    customer_email = 'some-email@example.org'
    fake_session = 'fake session'
    fake_product = {
        'product': 'some-product-id',
        'currency': 'some-currency',
        'recurring': {'interval': 'month', 'interval_count': 1},
    }

    with mock.patch(
        'olympia.promoted.utils.stripe.checkout.Session.create'
    ) as stripe_create, mock.patch(
        'olympia.promoted.utils.stripe.Price.retrieve'
    ) as stripe_retrieve:
        stripe_create.return_value = fake_session
        stripe_retrieve.return_value = fake_product

        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=['card'],
            mode='subscription',
            cancel_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_cancel',
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    'devhub.addons.onboarding_subscription_success',
                    args=[addon.id],
                )
            ),
            line_items=[
                {
                    'price_data': {
                        'product': fake_product['product'],
                        'currency': fake_product['currency'],
                        'recurring': {
                            'interval': fake_product['recurring']['interval'],
                            'interval_count': fake_product['recurring'][
                                'interval_count'
                            ],
                        },
                        'unit_amount': onboarding_rate,
                    },
                    'quantity': 1,
                }
            ],
            customer_email=customer_email,
        )


def test_create_stripe_customer_portal():
    addon = addon_factory()
    customer_id = 'some-customer-id'
    fake_portal = 'fake-return-value'

    with mock.patch(
        'olympia.promoted.utils.stripe.billing_portal.Session.create'
    ) as create_portal_mock:
        create_portal_mock.return_value = fake_portal

        portal = create_stripe_customer_portal(customer_id=customer_id, addon=addon)

        assert portal == fake_portal
        create_portal_mock.assert_called_once_with(
            customer=customer_id,
            return_url=absolutify(reverse('devhub.addons.edit', args=[addon.slug])),
        )


@override_settings(STRIPE_API_WEBHOOK_SECRET='webhook-secret')
def test_create_stripe_webhook_event():
    fake_event = 'fake-event'
    payload = 'some payload'
    sig_header = 'some sig_header'

    with mock.patch(
        'olympia.promoted.utils.stripe.Webhook.construct_event'
    ) as stripe_construct_event:
        stripe_construct_event.return_value = fake_event

        event = create_stripe_webhook_event(payload=payload, sig_header=sig_header)

        assert event == fake_event
        stripe_construct_event.assert_called_once_with(
            payload,
            sig_header,
            'webhook-secret',
        )


def test_retrieve_stripe_subscription():
    stripe_subscription_id = 'some stripe subscription id'
    sub = PromotedSubscription(stripe_subscription_id=stripe_subscription_id)
    fake_subscription = 'fake-stripe-subscription'

    with mock.patch(
        'olympia.promoted.utils.stripe.Subscription.retrieve'
    ) as stripe_retrieve:
        stripe_retrieve.return_value = fake_subscription

        stripe_sub = retrieve_stripe_subscription(subscription=sub)

        assert stripe_sub == fake_subscription
        stripe_retrieve.assert_called_once_with(stripe_subscription_id)


def test_retrieve_stripe_subscription_for_invoice():
    invoice_id = 'invoice-id'
    subscription_id = 'subscription-id'
    fake_invoice = {'subscription': subscription_id}
    fake_subscription = 'fake-stripe-subscription'

    with mock.patch(
        'olympia.promoted.utils.stripe.Invoice.retrieve'
    ) as invoice_mock, mock.patch(
        'olympia.promoted.utils.stripe.Subscription.retrieve'
    ) as subscription_mock:
        invoice_mock.return_value = fake_invoice
        subscription_mock.return_value = fake_subscription

        sub = retrieve_stripe_subscription_for_invoice(invoice_id=invoice_id)

        assert sub == fake_subscription
        invoice_mock.assert_called_once_with(invoice_id)
        subscription_mock.assert_called_once_with(subscription_id)
