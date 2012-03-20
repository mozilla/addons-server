import json

import jingo
import jwt
from session_csrf import anonymous_csrf
from waffle.decorators import waffle_switch

from django import http

from amo.decorators import login_required


def decode_request(signed_request):
    app_req = jwt.decode(str(signed_request), verify=False)
    app_req = json.loads(app_req)

    # TODO(Kumar) using the app key, look up the app's secret and verify the
    # request was encoded with the same secret.

    # secret = AppSecrets.objects.get(app_key=app_req['iss'])
    # jwt.decode(signed_request, secret, verify=True)
    return app_req


@anonymous_csrf
@waffle_switch('in-app-payments-ui')
def pay_start(request):
    signed_req = request.GET.get('req')
    if not signed_req:
        return http.HttpResponseBadRequest()
    decoded_req = decode_request(signed_req)
    data = dict(price=decoded_req['request']['price'],
                currency=decoded_req['request']['currency'],
                item=decoded_req['request']['name'],
                description=decoded_req['request']['description'],
                signed_request=signed_req)
    return jingo.render(request, 'payments/pay_start.html', data)


@anonymous_csrf
@login_required
@waffle_switch('in-app-payments-ui')
def pay(request):
    signed_req = request.POST.get('req')
    if not signed_req:
        return http.HttpResponseBadRequest()
    # decoded_req = decode_request(signed_req)

    # Do Paypal stuff!

    data = {}
    return jingo.render(request, 'payments/thanks_for_payment.html', data)
