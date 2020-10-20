import stripe

from django.conf import settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import SPONSORED, VERIFIED


def create_or_retrieve_stripe_checkout_session(subscription, customer_email):
    if subscription.stripe_session_id:
        return retrieve_stripe_checkout_session(subscription)

    price_id = {
        SPONSORED.id: settings.STRIPE_API_SPONSORED_PRICE_ID,
        VERIFIED.id: settings.STRIPE_API_VERIFIED_PRICE_ID,
    }.get(subscription.promoted_addon.group_id)

    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    return stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        cancel_url=absolutify(
            reverse(
                "devhub.addons.onboarding_subscription_cancel",
                args=[subscription.promoted_addon.addon_id],
            )
        ),
        success_url=absolutify(
            reverse(
                "devhub.addons.onboarding_subscription_success",
                args=[subscription.promoted_addon.addon_id],
            )
        ),
        line_items=[{"price": price_id, "quantity": 1}],
        customer_email=customer_email,
    )


def retrieve_stripe_checkout_session(subscription):
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    return stripe.checkout.Session.retrieve(subscription.stripe_session_id)
