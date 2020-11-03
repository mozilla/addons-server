import stripe

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.status import HTTP_202_ACCEPTED, HTTP_400_BAD_REQUEST

import olympia.core.logger

from .utils import create_stripe_webhook_event


log = olympia.core.logger.getLogger("z.promoted")


@api_view(["POST"])
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = create_stripe_webhook_event(
            payload=payload, sig_header=sig_header
        )
    except stripe.error.SignatureVerificationError:
        log.exception("received stripe event with invalid signature")
        return Response(status=HTTP_400_BAD_REQUEST)
    except ValueError:
        log.exception("received stripe event with invalid payload")
        return Response(status=HTTP_400_BAD_REQUEST)

    log.info('Received stripe event type: "%s".', event.type)

    return Response(status=HTTP_202_ACCEPTED)
