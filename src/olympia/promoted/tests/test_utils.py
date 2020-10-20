from unittest import mock

from django.conf import settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import SPONSORED
from olympia.promoted.models import PromotedSubscription, PromotedAddon
from olympia.promoted.utils import (
    create_or_retrieve_stripe_checkout_session,
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


def test_create_or_retrieve_stripe_checkout_session():
    addon = addon_factory()
    promoted_addon = PromotedAddon.objects.create(
        addon=addon, group_id=SPONSORED.id
    )
    sub = PromotedSubscription.objects.filter(
        promoted_addon=promoted_addon
    ).get()
    customer_email = "some-email@example.org"

    with mock.patch(
        "olympia.promoted.utils.stripe.checkout.Session.create"
    ) as stripe_create:
        stripe_create.return_value = "fake session"
        session = create_or_retrieve_stripe_checkout_session(
            subscription=sub, customer_email=customer_email
        )

        assert session == "fake session"
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
                    "price": settings.STRIPE_API_SPONSORED_PRICE_ID,
                    "quantity": 1,
                }
            ],
            customer_email=customer_email,
        )


def test_create_or_retrieve_stripe_checkout_session_with_existing_id():
    stripe_session_id = "some stripe session id"
    sub = PromotedSubscription(stripe_session_id=stripe_session_id)

    with mock.patch(
        "olympia.promoted.utils.stripe.checkout.Session.create"
    ) as stripe_create, mock.patch(
        "olympia.promoted.utils.retrieve_stripe_checkout_session"
    ) as retrieve:
        create_or_retrieve_stripe_checkout_session(
            subscription=sub, customer_email="doesnotmatter@example.org"
        )

        stripe_create.assert_not_called()
        retrieve.assert_called_once_with(sub)
