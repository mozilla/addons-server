import functools
import json

import jingo
import jwt
from session_csrf import anonymous_csrf
from waffle.decorators import waffle_switch
import lxml
import lxml.html

from django import http
from django.conf import settings

from amo.decorators import login_required


def remote_jsonp_view(f):
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        response = f(request, *args, **kw)
        if response.status_code != 200:
            return response
        callback = request.GET.get('callback', 'callback')

        # Make all URLs absolute.
        # If we can get the whole thing working in an iframe then we won't
        # need this. If we do then there is probably a more direct way.
        html = lxml.html.make_links_absolute(response.content,
                                             settings.SITE_URL)

        return http.HttpResponse('%s(%s)' % (callback, json.dumps(html)),
                                 content_type='application/javascript')
    return wrapper


def decode_request(signed_request):
    app_req = jwt.decode(str(signed_request), verify=False)
    app_req = json.loads(app_req)

    # TODO(Kumar) using the app key, look up the app's secret and verify the
    # request was encoded with the same secret.

    # secret = AppSecrets.objects.get(app_key=app_req['iss'])
    # jwt.decode(signed_request, secret, verify=True)
    return app_req


@anonymous_csrf
@remote_jsonp_view
@waffle_switch('in-app-payments')
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
@remote_jsonp_view
@waffle_switch('in-app-payments')
def pay(request):
    signed_req = request.GET.get('req')
    if not signed_req:
        return http.HttpResponseBadRequest()
    # decoded_req = decode_request(signed_req)

    # Do Paypal stuff!

    data = {}
    return jingo.render(request, 'payments/thanks_for_payment.html', data)


@remote_jsonp_view
@waffle_switch('in-app-payments')
def inject_styles(request):
    return jingo.render(request, 'payments/inject_styles.html', {})
