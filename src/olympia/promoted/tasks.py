import datetime

import olympia.core.logger

from django.conf import settings
from django.template import loader

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.constants.promoted import NOT_PROMOTED

from .models import PromotedSubscription
from .utils import retrieve_stripe_subscription_for_invoice


log = olympia.core.logger.getLogger('z.promoted.task')


@task
def on_stripe_charge_failed(event):
    event_id = event.get('id')
    event_type = event.get('type')

    if event_type != 'charge.failed':
        log.error('invalid event "%s" received (event_id=%s).', event_type, event_id)
        return

    # This event should contain a `charge` object.
    charge = event.get('data', {}).get('object')
    if not charge:
        log.error('no charge object in event (event_id=%s).', event_id)
        return

    charge_id = charge['id']
    log.info('received "%s" event with charge_id=%s.', event_type, charge_id)

    # It is possible that a `charge` object isn't bound to an invoice, e.g.,
    # when a Stripe admin manually attempts to charge a customer.
    if not charge['invoice']:
        log.error('"charge.failed" events without an invoice are not supported')
        return

    try:
        # Retrieve the `PromotedSubscription` for the current `charge` object.
        # We need to retrieve the Stripe Subscription first (via the Stripe
        # Invoice because a Stripe Charge isn't directly linked to a
        # Subscription).
        stripe_sub = retrieve_stripe_subscription_for_invoice(
            invoice_id=charge['invoice']
        )
        subscription_id = stripe_sub['id']
        log.debug(
            'retrieved stripe subscription with subscription_id=%s.',
            subscription_id,
        )

        sub = PromotedSubscription.objects.get(stripe_subscription_id=subscription_id)
    except PromotedSubscription.DoesNotExist:
        log.error(
            'received a "%s" event (event_id=%s) for a non-existent'
            ' promoted subscription (subscription_id=%s).',
            event_type,
            event_id,
            subscription_id,
        )
        return
    except Exception:
        log.exception(
            'error while trying to retrieve a subscription for "%s" '
            'event with event_id=%s and charge_id=%s.',
            event_type,
            event_id,
            charge_id,
        )
        return

    addon = sub.promoted_addon.addon

    # Create the Stripe URL pointing to the Stripe subscription.
    stripe_sub_url = settings.STRIPE_DASHBOARD_URL
    if not stripe_sub['livemode']:
        stripe_sub_url = stripe_sub_url + '/test'
    stripe_sub_url = f'{stripe_sub_url}/subscriptions/{subscription_id}'

    subject = f'Stripe payment failure detected for add-on: {addon.name}'
    template = loader.get_template('promoted/emails/stripe_charge_failed.txt')
    context = {
        'addon_url': absolutify(addon.get_detail_url()),
        'admin_url': absolutify(
            reverse(
                'admin:discovery_promotedaddon_change',
                args=[sub.promoted_addon_id],
            )
        ),
        'stripe_sub_url': stripe_sub_url,
    }

    send_mail(
        subject,
        template.render(context),
        from_email=settings.ADDONS_EMAIL,
        recipient_list=[settings.VERIFIED_ADDONS_EMAIL],
    )


@task
@use_primary_db
def on_stripe_customer_subscription_deleted(event):
    event_id = event.get('id')
    event_type = event.get('type')

    if event_type != 'customer.subscription.deleted':
        log.error('invalid event "%s" received (event_id=%s).', event_type, event_id)
        return

    # This event should contain a `subscription` object.
    subscription = event.get('data', {}).get('object')
    if not subscription:
        log.error('no subscription object in event (event_id=%s).', event_id)
        return

    subscription_id = subscription['id']
    log.info(
        'received "%s" event with subscription_id=%s.',
        event_type,
        subscription_id,
    )

    try:
        sub = PromotedSubscription.objects.get(stripe_subscription_id=subscription_id)
    except PromotedSubscription.DoesNotExist:
        log.exception(
            'received a "%s" event (event_id=%s) for a non-existent '
            'promoted subscription (subscription_id=%s).',
            event_type,
            event_id,
            subscription_id,
        )
        return

    if sub.cancelled_at:
        log.info(
            'PromotedSubscription %s already cancelled, ignoring event '
            '(event_id=%s).',
            sub.id,
            event_id,
        )
        return

    sub.update(
        cancelled_at=datetime.datetime.fromtimestamp(subscription['canceled_at'])
    )
    log.info('PromotedSubscription %s has been marked as cancelled.', sub.id)

    # TODO: this should trigger resigning somehow, see:
    # https://github.com/mozilla/addons-server/issues/15921
    sub.promoted_addon.update(group_id=NOT_PROMOTED.id)
    log.info(
        'Addon %s is not promoted anymore (PromotedAddon=%s and '
        'PromotedSubscription=%s).',
        sub.promoted_addon.addon_id,
        sub.promoted_addon.id,
        sub.id,
    )


@task
def on_stripe_charge_succeeded(event):
    event_id = event.get('id')
    event_type = event.get('type')

    if event_type != 'charge.succeeded':
        log.error('invalid event "%s" received (event_id=%s).', event_type, event_id)
        return

    # This event should contain a `charge` object.
    charge = event.get('data', {}).get('object')
    if not charge:
        log.error('no charge object in event (event_id=%s).', event_id)
        return

    charge_id = charge['id']
    log.info('received "%s" event with charge_id=%s.', event_type, charge_id)

    # Create the Stripe URL pointing to the Stripe payment.
    stripe_payment_url = settings.STRIPE_DASHBOARD_URL
    if not charge.get('livemode'):
        stripe_payment_url = stripe_payment_url + '/test'
    stripe_payment_url = f"{stripe_payment_url}/payments/{charge.get('payment_intent')}"

    subject = 'Stripe payment succeeded'
    template = loader.get_template('promoted/emails/stripe_charge_succeeded.txt')
    context = {
        'stripe_payment_url': stripe_payment_url,
    }

    send_mail(
        subject,
        template.render(context),
        from_email=settings.ADDONS_EMAIL,
        recipient_list=[settings.VERIFIED_ADDONS_EMAIL],
    )
