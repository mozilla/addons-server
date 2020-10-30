import pytest

from unittest import mock

from django.test.utils import override_settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import SPONSORED, RECOMMENDED
from olympia.promoted.models import PromotedSubscription, PromotedAddon
from olympia.promoted.utils import (
    create_stripe_checkout_session,
    retrieve_stripe_checkout_session,
)


def test_retrieve_stripe_checkout_session():
    stripe_session_id = "some stripe session id"
    sub = PromotedSubscription(stripe_session_id=stripe_session_id)

    with mock.patch(
        "olympia.promoted.utils.stripe.checkout.Session.retrieve"
    ) as stripe_retrieve:
        retrieve_stripe_checkout_session(subscription=sub)

        stripe_retrieve.assert_called_once_with(stripe_session_id)


@override_settings(STRIPE_API_SPONSORED_PRICE_ID="sponsored-price-id")
def test_create_stripe_checkout_session():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(
        addon=addon, group_id=SPONSORED.id
    )
    sub = PromotedSubscription.objects.filter(
        promoted_addon=promoted_addon
    ).get()
    customer_email = "some-email@example.org"
    fake_session = "fake session"

    with mock.patch(
        "olympia.promoted.utils.stripe.checkout.Session.create"
    ) as stripe_create:
        stripe_create.return_value = fake_session
        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=["card"],
            mode="subscription",
            cancel_url=absolutify(
                reverse(
                    "devhub.addons.onboarding_subscription_cancel",
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    "devhub.addons.onboarding_subscription_success",
                    args=[addon.id],
                )
            ),
            line_items=[{"price": "sponsored-price-id", "quantity": 1}],
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
            subscription=sub, customer_email="doesnotmatter@example.org"
        )


@override_settings(STRIPE_API_SPONSORED_PRICE_ID="sponsored-price-id")
def test_create_stripe_checkout_session_with_custom_rate():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(
        addon=addon, group_id=SPONSORED.id
    )
    sub = PromotedSubscription.objects.filter(
        promoted_addon=promoted_addon
    ).get()
    # Set a custom onboarding rate, in cents.
    onboarding_rate = 1234
    sub.update(onboarding_rate=onboarding_rate)
    customer_email = "some-email@example.org"
    fake_session = "fake session"
    fake_product = {
        "product": "some-product-id",
        "currency": "some-currency",
        "recurring": {"interval": "month", "interval_count": 1},
    }

    with mock.patch(
        "olympia.promoted.utils.stripe.checkout.Session.create"
    ) as stripe_create, mock.patch(
        "olympia.promoted.utils.stripe.Price.retrieve"
    ) as stripe_retrieve:
        stripe_create.return_value = fake_session
        stripe_retrieve.return_value = fake_product

        session = create_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == fake_session
        stripe_create.assert_called_once_with(
            payment_method_types=["card"],
            mode="subscription",
            cancel_url=absolutify(
                reverse(
                    "devhub.addons.onboarding_subscription_cancel",
                    args=[addon.id],
                )
            ),
            success_url=absolutify(
                reverse(
                    "devhub.addons.onboarding_subscription_success",
                    args=[addon.id],
                )
            ),
            line_items=[
                {
                    "price_data": {
                        "product": fake_product["product"],
                        "currency": fake_product["currency"],
                        "recurring": {
                            "interval": fake_product["recurring"]["interval"],
                            "interval_count": fake_product["recurring"][
                                "interval_count"
                            ],
                        },
                        "unit_amount": onboarding_rate,
                    },
                    "quantity": 1,
                }
            ],
            customer_email=customer_email,
        )
