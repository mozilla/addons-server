import stripe

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.status import HTTP_202_ACCEPTED, HTTP_400_BAD_REQUEST

import olympia.core.logger

from .tasks import (
    on_stripe_charge_failed,
    on_stripe_charge_succeeded,
    on_stripe_customer_subscription_deleted,
)
from .utils import create_stripe_webhook_event


log = olympia.core.logger.getLogger('z.promoted')


# This dict maps a Stripe event type with a Celery task that handles events of
# that type.
ON_STRIPE_EVENT_TASKS = {
    'charge.failed': on_stripe_charge_failed,
    'charge.succeeded': on_stripe_charge_succeeded,
    'customer.subscription.deleted': on_stripe_customer_subscription_deleted,
}


@api_view(['POST'])
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = create_stripe_webhook_event(payload=payload, sig_header=sig_header)
    except stripe.error.SignatureVerificationError:
        log.exception('received stripe event with invalid signature')
        return Response(status=HTTP_400_BAD_REQUEST)
    except ValueError:
        log.exception('received stripe event with invalid payload')
        return Response(status=HTTP_400_BAD_REQUEST)

    task = ON_STRIPE_EVENT_TASKS.get(event.type)

    if task:
        task.delay(event=event)
    else:
        # This would only happen if a Stripe admin updates the configured
        # webhook to send new events (because we have to select the events we
        # want in the Stripe settings).
        log.info('received unhandled stripe event type: "%s".', event.type)

    return Response(status=HTTP_202_ACCEPTED)
