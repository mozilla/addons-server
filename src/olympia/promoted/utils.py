import stripe

from django.conf import settings

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.constants.promoted import (
    BILLING_PERIOD_MONTHLY,
    BILLING_PERIOD_YEARLY,
    SPONSORED,
    VERIFIED,
)


def get_stripe_price_id_for_subscription(subscription):
    if subscription.onboarding_period == BILLING_PERIOD_YEARLY:
        price_id_by_group_id = {
            SPONSORED.id: settings.STRIPE_API_SPONSORED_YEARLY_PRICE_ID,
            VERIFIED.id: settings.STRIPE_API_VERIFIED_YEARLY_PRICE_ID,
        }
    elif subscription.onboarding_period == BILLING_PERIOD_MONTHLY:
        price_id_by_group_id = {
            SPONSORED.id: settings.STRIPE_API_SPONSORED_MONTHLY_PRICE_ID,
            VERIFIED.id: settings.STRIPE_API_VERIFIED_MONTHLY_PRICE_ID,
        }
    else:
        # Default billing rate/period configuration for each promoted group.
        price_id_by_group_id = {
            SPONSORED.id: settings.STRIPE_API_SPONSORED_YEARLY_PRICE_ID,
            VERIFIED.id: settings.STRIPE_API_VERIFIED_MONTHLY_PRICE_ID,
        }

    return price_id_by_group_id.get(subscription.promoted_addon.group_id)


def create_stripe_checkout_session(subscription, customer_email):
    """This function creates a Stripe Checkout Session object for a given
    subscription. The `customer_email` is passed to Stripe to autofill the
    input field on the Checkout page.

    This function might raise if the promoted group isn't supported or the API
    call has failed."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY

    price_id = get_stripe_price_id_for_subscription(subscription)
    if not price_id:
        raise ValueError(
            'No price ID for promoted group ID: {}.'.format(
                subscription.promoted_addon.group_id
            )
        )

    if subscription.onboarding_rate:
        # When we have a custom onboarding rate, we have to retrieve the Stripe
        # Product associated with the default Stripe Price first, so that we
        # can pass the Product ID to Stripe with a custom amount.
        price = stripe.Price.retrieve(price_id)

        line_item = {
            'price_data': {
                'product': price.get('product'),
                'currency': price.get('currency'),
                'recurring': {
                    'interval': price.get('recurring', {}).get('interval'),
                    'interval_count': price.get('recurring', {}).get('interval_count'),
                },
                'unit_amount': subscription.onboarding_rate,
            },
            'quantity': 1,
        }
    else:
        # The default price will be used for this subscription.
        line_item = {'price': price_id, 'quantity': 1}

    return stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='subscription',
        cancel_url=absolutify(
            reverse(
                'devhub.addons.onboarding_subscription_cancel',
                args=[subscription.promoted_addon.addon_id],
            )
        ),
        success_url=absolutify(
            reverse(
                'devhub.addons.onboarding_subscription_success',
                args=[subscription.promoted_addon.addon_id],
            )
        ),
        line_items=[line_item],
        customer_email=customer_email,
    )


def retrieve_stripe_checkout_session(subscription):
    """This function returns a Stripe Checkout Session object or raises an
    error when the session does not exist or the API call has failed.

    This function should only be used during the Checkout process."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    return stripe.checkout.Session.retrieve(subscription.stripe_session_id)


def retrieve_stripe_subscription(subscription):
    """This function returns a Stripe Subscription object or raises errors."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    return stripe.Subscription.retrieve(subscription.stripe_subscription_id)


def create_stripe_customer_portal(customer_id, addon):
    """This function creates a Stripe Customer Portal object or raises an error
    when the session does not exist or the API call has failed."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    return stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=absolutify(reverse('devhub.addons.edit', args=[addon.slug])),
    )


def create_stripe_webhook_event(payload, sig_header):
    """This function returns a Stripe Webhook Event object or raises errors."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    webhook_secret = settings.STRIPE_API_WEBHOOK_SECRET
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)


def retrieve_stripe_subscription_for_invoice(invoice_id):
    """This function returns a Stripe Subscription object or raises errors."""
    stripe.api_key = settings.STRIPE_API_SECRET_KEY
    invoice = stripe.Invoice.retrieve(invoice_id)
    return stripe.Subscription.retrieve(invoice['subscription'])
