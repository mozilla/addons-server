# -*- coding: utf-8 -*-
import urllib
import urlparse

from django.conf import settings
from django.utils.http import urlquote

import commonware.log
from django_statsd.clients import statsd
import requests

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import log_cef
from tower import ugettext as _


class PaypalError(Exception):
    # The generic Paypal error and message.
    def __init__(self, message='', id=None, paypal_data=None):
        super(PaypalError, self).__init__(message)
        self.id = id
        self.paypal_data = paypal_data
        self.default = _('There was an error communicating with PayPal. '
                         'Please try again later.')

    def __str__(self):
        msg = self.message
        if not msg:
            msg = messages.get(self.id, self.default)
        return msg.encode('utf8') if isinstance(msg, unicode) else msg


class PaypalDataError(PaypalError):
    # Some of the data passed to Paypal was incorrect. We'll catch them and
    # re-raise as a PaypalError so they can be easily caught.
    pass


class AuthError(PaypalError):
    # We've got the settings wrong on our end.
    pass


class CurrencyError(PaypalError):
    # This currency was bad.

    def __str__(self):
        default = _('There was an error with this currency.')
        if self.paypal_data and 'currencyCode' in self.paypal_data:
            try:
                return (messages.get(self.id) %
                    amo.PAYPAL_CURRENCIES[self.paypal_data['currencyCode']])
                # TODO: figure this out.
            except:
                pass
        return default


errors = {'520003': AuthError}
for number in ['559044', '580027', '580022']:
    errors[number] = CurrencyError

# Here you can map PayPal error messages into hopefully more useful
# error messages.
messages = {'589023': _("The amount is too small for conversion "
                        "into the receiver's currency."),
            '579033': _('The buyer and seller must have different '
                        'PayPal accounts.'),
            #L10n: {0} is the currency.
            '559044': _(u'The seller does not accept payments in %s.')}

paypal_log = commonware.log.getLogger('z.paypal')


def should_ignore_paypal():
    """
    Returns whether to skip PayPal communications for development
    purposes or not.
    """
    return settings.DEBUG and 'sandbox' not in settings.PAYPAL_PERMISSIONS_URL


def get_paykey(data):
    """
    Gets a paykey from Paypal. Need to pass in the following in data:
    pattern: the reverse pattern to resolve
    email: who the money is going to (required)
    amount: the amount of money (required)
    ip: ip address of end user (required)
    uuid: contribution_uuid (required)
    memo: any nice message (optional)
    qs: anything you want to append to the complete or cancel (optional)
    currency: valid paypal currency, defaults to USD (optional)
    """
    if data['pattern']:
        complete = reverse(data['pattern'], args=[data['slug'], 'complete'])
        cancel = reverse(data['pattern'], args=[data['slug'], 'cancel'])
    else:
        # If there's no pattern given, just fake some urls.
        complete = cancel = settings.SITE_URL + '/paypal/dummy/'

    qs = {'uuid': data['uuid']}
    if 'qs' in data:
        qs.update(data['qs'])
    uuid_qs = urllib.urlencode(qs)

    paypal_data = {
        'actionType': 'PAY',
        'currencyCode': data.get('currency', 'USD'),
        'cancelUrl': absolutify('%s?%s' % (cancel, uuid_qs)),
        'returnUrl': absolutify('%s?%s' % (complete, uuid_qs)),
        'trackingId': data['uuid'],
        'ipnNotificationUrl': absolutify(reverse('amo.paypal')),
        'receiverList.receiver(0).email': data['email'],
        'receiverList.receiver(0).amount': data['amount'],
        'receiverList.receiver(0).invoiceID': 'mozilla-%s' % data['uuid'],
        'receiverList.receiver(0).primary': 'TRUE',
        'receiverList.receiver(0).paymentType': 'DIGITALGOODS',
        'requestEnvelope.errorLanguage': 'US'
    }

    if data.get('memo'):
        paypal_data['memo'] = data['memo']

    with statsd.timer('paypal.paykey.retrieval'):
        response = _call(settings.PAYPAL_PAY_URL + 'Pay', paypal_data,
                         ip=data['ip'])

    return response['payKey'], response['paymentExecStatus']


def check_purchase(paykey):
    """
    When a purchase is complete checks paypal that the purchase has gone
    through.
    """
    with statsd.timer('paypal.payment.details'):
        try:
            response = _call(settings.PAYPAL_PAY_URL + 'PaymentDetails',
                             {'payKey': paykey})
        except PaypalError:
            paypal_log.error('Payment details error', exc_info=True)
            return False

    return response['status']


def _nvp_dump(data):
    """
    Dumps a dict out into NVP pairs suitable for PayPal to consume.
    """
    out = []
    escape = lambda k, v: '%s=%s' % (k, urlquote(v))
    # This must be sorted for chained payments to work correctly.
    for k, v in sorted(data.items()):
        if isinstance(v, (list, tuple)):
            out.extend([escape('%s(%s)' % (k, x), v_)
                        for x, v_ in enumerate(v)])
        else:
            out.append(escape(k, v))

    return '&'.join(out)


def _call(url, paypal_data, ip=None):
    headers = {}
    auth = settings.PAYPAL_EMBEDDED_AUTH
    if 'requestEnvelope.errorLanguage' not in paypal_data:
        paypal_data['requestEnvelope.errorLanguage'] = 'en_US'

    # We always need these headers.
    for key, value in [
            ('application-id', settings.PAYPAL_APP_ID),
            ('request-data-format', 'NV'),
            ('response-data-format', 'NV'),
            ('application-id', settings.PAYPAL_APP_ID),
            ('security-userid', auth['USER']),
            ('security-password', auth['PASSWORD']),
            ('security-signature', auth['SIGNATURE'])]:
        headers['X-PAYPAL-%s' % key.upper()] = value

    if ip:
        headers['X-PAYPAL-DEVICE-IPADDRESS'] = ip

    # Warning, a urlencode will not work with chained payments, it must
    # be sorted and the key should not be escaped.
    try:
        data = _nvp_dump(paypal_data)
        feeddata = requests.post(url, headers=headers, timeout=10,
                                 data=data,
                                 verify=True,
                                 cert=settings.PAYPAL_CERT)
    except AuthError, error:
        paypal_log.error('Authentication error: %s' % error)
        raise
    except Exception, error:
        paypal_log.error('HTTP Error: %s' % error)
        # We'll log the actual error and then raise a Paypal error.
        # That way all the calling methods only have catch a Paypal error,
        # the fact that there may be say, a http error, is internal to this
        # method.
        raise PaypalError

    response = dict(urlparse.parse_qsl(feeddata.text))

    if 'error(0).errorId' in response:
        id_, msg = response['error(0).errorId'], response['error(0).message']
        paypal_log.error('Paypal Error (%s): %s' % (id_, msg))
        raise errors.get(id_, PaypalError)(id=id_, paypal_data=paypal_data)

    return response


def check_paypal_id(name):
    """
    Use the button API to check if name is a valid Paypal id.

    Returns bool(valid), str(msg).  msg will be None if there wasn't an error.
    """
    d = dict(version=settings.PAYPAL_API_VERSION,
             buttoncode='cleartext',
             buttontype='donate',
             method='BMCreateButton',
             l_buttonvar0='business=%s' % name)
    d['user'] = settings.PAYPAL_EMBEDDED_AUTH['USER']
    d['pwd'] = settings.PAYPAL_EMBEDDED_AUTH['PASSWORD']
    d['signature'] = settings.PAYPAL_EMBEDDED_AUTH['SIGNATURE']
    r = requests.get(settings.PAYPAL_API_URL, params=d, timeout=10)
    response = dict(urlparse.parse_qsl(r.text))
    valid = response['ACK'] == 'Success'
    msg = None if valid else response['L_LONGMESSAGE0']
    return valid, msg


def paypal_log_cef(request, addon, uuid, msg, caps, longer):
    log_cef('Paypal %s' % msg, 5, request,
            username=request.amo_user,
            signature='PAYPAL%s' % caps,
            msg=longer, cs2=addon.name, cs2Label='PaypalTransaction',
            cs4=uuid, cs4Label='TxID')
