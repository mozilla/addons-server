import stripe

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

import olympia.core.logger

from olympia.amo.decorators import post_required

from .utils import create_stripe_webhook_event


log = olympia.core.logger.getLogger("z.promoted")


@post_required
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
        return HttpResponse(status=400)
    except ValueError:
        log.exception("received stripe event with invalid payload")
        return HttpResponse(status=400)

    log.info('Received stripe event type: "%s".', event.type)

    return HttpResponse(status=200)
