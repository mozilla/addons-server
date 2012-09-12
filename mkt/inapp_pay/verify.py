import calendar
from datetime import datetime
import json
import sys
import time

from django import forms
from django.conf import settings

import jwt
from django_statsd.clients import statsd

import amo
from market.models import Price

from .forms import PaymentForm, ContributionForm
from .models import InappConfig


class InappPaymentError(Exception):
    """An error occurred while processing an in-app payment."""

    def __init__(self, msg, app_id=None):
        self.app_id = app_id
        if self.app_id:
            msg = '%s (app ID=%r)' % (msg, self.app_id)
        super(Exception, self).__init__(msg)


class UnknownAppError(InappPaymentError):
    """The application ID is not known."""


class RequestVerificationError(InappPaymentError):
    """The payment request could not be verified."""


class RequestExpired(InappPaymentError):
    """The payment request expired."""


class AppPaymentsDisabled(InappPaymentError):
    """In-app payment functionality for this app has been disabled."""


class AppPaymentsRevoked(InappPaymentError):
    """In-app payment functionality for this app has been revoked."""


class InvalidRequest(InappPaymentError):
    """The payment request has malformed or missing information."""


def _re_raise_as(NewExc, *args, **kw):
    """Raise a new exception using the preserved traceback of the last one."""
    etype, val, tb = sys.exc_info()
    raise NewExc(*args, **kw), None, tb


def verify_request(signed_request):
    """
    Verifies a signed in-app payment request.

    Returns the trusted JSON data from the original request.
    JWT spec: http://openid.net/specs/draft-jones-json-web-token-07.html

    One extra key, _config, is added to the returned JSON.
    This is the InappConfig instance.

    When there's an error, an exception derived from InappPaymentError
    will be raised.
    """
    try:
        signed_request = str(signed_request)  # must be base64 encoded bytes
    except UnicodeEncodeError, exc:
        _re_raise_as(RequestVerificationError,
                     'Non-ascii payment JWT: %s' % exc)
    try:
        app_req = jwt.decode(signed_request, verify=False)
    except jwt.DecodeError, exc:
        _re_raise_as(RequestVerificationError, 'Invalid payment JWT: %s' % exc)
    try:
        app_req = json.loads(app_req)
    except ValueError, exc:
        _re_raise_as(RequestVerificationError,
                     'Invalid JSON for payment JWT: %s' % exc)

    app_id = app_req.get('iss')

    # Verify the signature:
    try:
        cfg = InappConfig.objects.get(public_key=app_id,
                                      addon__status=amo.STATUS_PUBLIC)
    except InappConfig.DoesNotExist:
        _re_raise_as(UnknownAppError, 'App does not exist or is not public',
                     app_id=app_id)
    if cfg.status == amo.INAPP_STATUS_REVOKED:
        raise AppPaymentsRevoked('Payments revoked', app_id=app_id)
    elif cfg.status != amo.INAPP_STATUS_ACTIVE:
        raise AppPaymentsDisabled('Payments disabled (status=%s)'
                                  % (cfg.status), app_id=app_id)
    app_req['_config'] = cfg

    try:
        with statsd.timer('inapp_pay.verify'):
            jwt.decode(signed_request, cfg.get_private_key(), verify=True)
    except jwt.DecodeError, exc:
        _re_raise_as(RequestVerificationError,
                     'Payment verification failed: %s' % exc,
                     app_id=app_id)

    # Check timestamps:
    try:
        expires = float(str(app_req.get('exp')))
        issued = float(str(app_req.get('iat')))
    except ValueError:
        _re_raise_as(RequestVerificationError,
                     'Payment JWT had an invalid exp (%r) or iat (%r) '
                     % (app_req.get('exp'), app_req.get('iat')),
                     app_id=app_id)
    now = calendar.timegm(time.gmtime())
    if expires < now:
        raise RequestExpired('Payment JWT expired: %s UTC < %s UTC '
                             '(issued at %s UTC)'
                             % (datetime.utcfromtimestamp(expires),
                                datetime.utcfromtimestamp(now),
                                datetime.utcfromtimestamp(issued)),
                             app_id=app_id)
    if issued < (now - 3600):  # issued more than an hour ago
        raise RequestExpired('Payment JWT iat expired: %s UTC < %s UTC '
                             % (datetime.utcfromtimestamp(issued),
                                datetime.utcfromtimestamp(now)),
                             app_id=app_id)
    try:
        not_before = float(str(app_req.get('nbf')))
    except ValueError:
        app_req['nbf'] = None  # this field is optional
    else:
        about_now = now + 300  # pad 5 minutes for clock skew
        if not_before >= about_now:
            raise InvalidRequest('Payment JWT cannot be processed before '
                                 '%s UTC (nbf must be < %s UTC)'
                                 % (datetime.utcfromtimestamp(not_before),
                                    datetime.utcfromtimestamp(about_now)),
                                 app_id=app_id)

    # Check JWT audience.
    audience = app_req.get('aud', None)
    if not audience:
        raise InvalidRequest('Payment JWT is missing aud (audience)',
                             app_id=app_id)
    if audience != settings.INAPP_MARKET_ID:
        raise InvalidRequest('Payment JWT aud (audience) must be set to %r; '
                             'got: %r' % (settings.INAPP_MARKET_ID,
                                          audience),
                             app_id=app_id)

    request = app_req.get('request', None)

    # Check payment details.
    if not isinstance(request, dict):
        raise InvalidRequest('Payment JWT is missing request dict: %r'
                             % request, app_id=app_id)
    for key in ('priceTier', 'name', 'description'):
        if key not in request:
            raise InvalidRequest('Payment JWT is missing request[%r]'
                                 % key, app_id=app_id)

    # Validate values for model integrity.
    key_trans = {'app_data': 'productdata'}
    for form in (PaymentForm(), ContributionForm()):
        for name, field in form.fields.items():
            if name in ('amount', 'currency'):
                # Since we're using price tiers we don't need to complain
                # about missing amount (which is price in the request)
                # or currency.
                continue
            req_field = key_trans.get(name, name)
            value = request[req_field]
            try:
                field.clean(value)
            except forms.ValidationError, exc:
                _re_raise_as(InvalidRequest,
                             u'request[%r] is invalid: %s' % (req_field, exc))

    # Validate the price tier.
    try:
        if not Price.objects.filter(pk=request['priceTier']).exists():
            raise InvalidRequest(
                    u'priceTier:%s is not a supported price tier. Consult the '
                    u'docs for all supported tiers: '
                    u'https://developer.mozilla.org/en/Apps/In-app_payments'
                    % request['priceTier'])
    except ValueError:
        _re_raise_as(InvalidRequest,
                     u'priceTier:%r is not a valid number'
                     % request['priceTier'])

    return app_req
