import contextlib
import socket
import time
import urllib
import urllib2
import urlparse

from django.conf import settings
from django.utils.http import urlencode

import commonware.log

from amo.helpers import absolutify
from amo.urlresolvers import reverse


class PaypalError(Exception):
    id = None


class AuthError(Exception):
    pass


errors = {'520003': AuthError}
paypal_log = commonware.log.getLogger('z.paypal')

def get_paykey(data):
    """
    Gets a paykey from Paypal. Need to pass in the following in data:
    return_url and cancel_url: where user goes back to (required)
    email: who the money is going to (required)
    amount: the amount of money (required)
    ip: ip address of end user (required)
    uuid: contribution_uuid (required)
    memo: any nice message
    """
    start = time.time()
    request = urllib2.Request(settings.PAYPAL_PAY_URL)
    for key, value in [
            ('security-userid', settings.PAYPAL_EMBEDDED_AUTH['USER']),
            ('security-password', settings.PAYPAL_EMBEDDED_AUTH['PASSWORD']),
            ('security-signature', settings.PAYPAL_EMBEDDED_AUTH['SIGNATURE']),
            ('application-id', settings.PAYPAL_APP_ID),
            ('device-ipaddress', data['ip']),
            ('request-data-format', 'NV'),
            ('response-data-format', 'NV')]:
        request.add_header('X-PAYPAL-%s' % key.upper(), value)

    paypal_data = {
        'actionType': 'PAY',
        'requestEnvelope.errorLanguage': 'US',
        'currencyCode': 'USD',
        'cancelUrl': data['cancel_url'],
        'returnUrl': data['return_url'],
        'receiverList.receiver(0).email': data['email'],
        'receiverList.receiver(0).amount': data['amount'],
        'receiverList.receiver(0).invoiceID': 'mozilla-%s' % data['uuid'],
        'receiverList.receiver(0).primary': 'TRUE',
        'receiverList.receiver(0).paymentType': 'DIGITALGOODS',
        'trackingId': data['uuid'],
        'ipnNotificationUrl': absolutify(reverse('amo.paypal'))}

    if data.get('memo'):
        paypal_data['memo'] = data['memo']

    opener = urllib2.build_opener()
    try:
        with socket_timeout(10):
            feeddata = opener.open(request, urlencode(paypal_data)).read()
    except Exception, error:
        paypal_log.error('HTTP Error: %s' % error)
        raise

    response = dict(urlparse.parse_qsl(feeddata))

    if 'error(0).errorId' in response:
        error = errors.get(response['error(0).errorId'], PaypalError)
        paypal_log.error('Paypal Error: %s' % response['error(0).message'])
        raise error(response['error(0).message'])

    paypal_log.info('Paypal got key: %s (%.2fs)' %
                    (response['payKey'], time.time() - start))
    return response['payKey']


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
    # TODO(andym): remove this once this is all live and settled down.
    if hasattr(settings, 'PAYPAL_CGI_AUTH'):
        d['user'] = settings.PAYPAL_CGI_AUTH['USER']
        d['pwd'] = settings.PAYPAL_CGI_AUTH['PASSWORD']
        d['signature'] = settings.PAYPAL_CGI_AUTH['SIGNATURE']
    else:
        # In production if PAYPAL_CGI_AUTH doesn't get defined yet,
        # fall back to the existing values.
        d.update(dict(user=settings.PAYPAL_USER,
                      pwd=settings.PAYPAL_PASSWORD,
                      signature=settings.PAYPAL_SIGNATURE))
    with socket_timeout(10):
        r = urllib.urlopen(settings.PAYPAL_API_URL, urlencode(d))
    response = dict(urlparse.parse_qsl(r.read()))
    valid = response['ACK'] == 'Success'
    msg = None if valid else response['L_LONGMESSAGE0']
    return valid, msg


@contextlib.contextmanager
def socket_timeout(timeout):
    """Context manager to temporarily set the default socket timeout."""
    old = socket.getdefaulttimeout()
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)
