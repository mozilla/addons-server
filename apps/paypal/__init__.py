# -*- coding: utf-8 -*-
import contextlib
from decimal import Decimal, InvalidOperation
import socket
import urllib
import urllib2
import urlparse
import re

from django.conf import settings
from django.utils.http import urlencode, urlquote

import commonware.log
from django_statsd.clients import statsd

import amo
from amo.helpers import absolutify, loc, urlparams
from amo.urlresolvers import reverse
from amo.utils import log_cef
from tower import ugettext as _


class PaypalError(Exception):
    # The generic Paypal error and message.
    def __init__(self, message='', id=None):
        super(PaypalError, self).__init__(message)
        self.id = id
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


class PreApprovalError(PaypalError):
    # Something went wrong in pre approval, there's usually not much
    # we can do about this.
    pass


class CurrencyError(PaypalError):
    # This currency was bad.
    pass


errors = {'520003': AuthError}
# See http://bit.ly/vWV525 for information on these values.
# Note that if you have and invalid preapproval key you get 580022, but this
# also occurs in other cases so don't assume its preapproval only.
for number in ['579024', '579025', '579026', '579027', '579028',
               '579030', '579031']:
    errors[number] = PreApprovalError
for number in ['580027', '580022']:
    errors[number] = CurrencyError

# Here you can map PayPal error messages into hopefully more useful
# error messages.
messages = {'589023': loc('The amount is too small for conversion '
                          "into the receiver's currency.")}


paypal_log = commonware.log.getLogger('z.paypal')


def should_ignore_paypal():
    """
    Returns whether to skip PayPal communications for development
    purposes or not.
    """
    return settings.DEBUG and 'sandbox' not in settings.PAYPAL_PERMISSIONS_URL


def add_receivers(chains, email, amount, uuid, preapproval=False):
    """
    Split a payment down into multiple receivers using the chains passed in.
    """
    try:
        remainder = Decimal(str(amount))
    except (UnicodeEncodeError, InvalidOperation), msg:
        raise PaypalDataError(msg)

    result = {}
    for number, chain in enumerate(chains, 1):
        percent, destination = chain
        this = (Decimal(str(float(amount) * (percent / 100.0)))
                .quantize(Decimal('.01')))
        remainder = remainder - this
        key = 'receiverList.receiver(%s)' % number
        result.update({
            '%s.email' % key: destination,
            '%s.amount' % key: str(this),
            '%s.primary' % key: 'false',
            # This is only done if there is a chained payment. Otherwise
            # it does not need to be set.
            'receiverList.receiver(0).primary': 'true',
            # Mozilla pays the fees, because we've got a special rate.
            'feesPayer': 'SECONDARYONLY'
        })
        if not preapproval:
            result['%s.paymentType' % key] = 'DIGITALGOODS'

    result.update({
        'receiverList.receiver(0).email': email,
        'receiverList.receiver(0).amount': str(amount),
        'receiverList.receiver(0).invoiceID': 'mozilla-%s' % uuid
    })

    # Adding DIGITALGOODS to a pre-approval triggers an error in PayPal.
    if not preapproval:
        result['receiverList.receiver(0).paymentType'] = 'DIGITALGOODS'

    return result


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
    complete = reverse(data['pattern'], args=[data['slug'], 'complete'])
    cancel = reverse(data['pattern'], args=[data['slug'], 'cancel'])

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
        'ipnNotificationUrl': absolutify(reverse('amo.paypal'))}

    receivers = (data.get('chains', ()), data['email'], data['amount'],
                 data['uuid'])

    if data.get('preapproval'):
        # The paypal_key might be empty if they have removed it.
        key = data['preapproval'].paypal_key
        if key:
            paypal_log.info('Using preapproval: %s' % data['preapproval'].pk)
            paypal_data['preapprovalKey'] = key

    paypal_data.update(add_receivers(*receivers,
                                preapproval='preapprovalKey' in paypal_data))

    if data.get('memo'):
        paypal_data['memo'] = data['memo']

    try:
        with statsd.timer('paypal.paykey.retrieval'):
            response = _call(settings.PAYPAL_PAY_URL + 'Pay', paypal_data,
                             ip=data['ip'])
    except PreApprovalError, e:
        # Let's retry just once without preapproval.
        paypal_log.error('Failed using preapproval, reason: %s' % e)
        # Now it's not a pre-approval, make sure we get the
        # DIGITALGOODS setting back in there.
        del paypal_data['preapprovalKey']
        paypal_data.update(add_receivers(*receivers))
        # If this fails, we won't try again, just fail.
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


def refund(paykey):
    """
    Refund a payment.

    Arguments: paykey of payment to refund

    Returns: A list of dicts containing the refund info for each
    receiver of the original payment.
    """
    OK_STATUSES = ['REFUNDED', 'REFUNDED_PENDING', 'ALREADY_REVERSED_OR_REFUNDED']
    with statsd.timer('paypal.payment.refund'):
        try:
            response = _call(settings.PAYPAL_PAY_URL + 'Refund',
                             {'payKey': paykey})
        except PaypalError:
            paypal_log.error('Refund error', exc_info=True)
            raise
        responses = []
        for k in response:
            g = re.match('refundInfoList.refundInfo\((\d+)\).(.*)', k)
            if g:
                i = int(g.group(1))
                subkey = g.group(2)
                while i >= len(responses):
                    responses.append({})
                responses[i][subkey] = response[k]
        for d in responses:
            if d['refundStatus'] not in OK_STATUSES:
                raise PaypalError('Bad refund status for %s: %s'
                                  % (d['receiver.email'],
                                     d['refundStatus']))
            paypal_log.debug('Refund successful for: %s, %s, %s' %
                             (paykey, d['receiver.email'], d['refundStatus']))

        return responses


def get_personal_data(token):
    """
    Ask PayPal for personal data based on the token. This makes two API
    calls to PayPal. It's assumed you've already done the check_permission
    call below.
    Documentation: http://bit.ly/xy5BTs and http://bit.ly/yRYbRx
    """
    def call(api, data):
        try:
            with statsd.timer('paypal.get.personal'):
                r = _call(settings.PAYPAL_PERMISSIONS_URL + api, data)
        except PaypalError, error:
            paypal_log.debug('Paypal returned an error when getting personal'
                             'data for token: %s... error: %s'
                             % (token[:10], error))
            raise
        return r

    # A mapping fo the api and the values passed to the API.
    calls = {
        'GetBasicPersonalData':
            {'attributeList.attribute':
                [amo.PAYPAL_PERSONAL[k] for k in
                    ['first', 'last', 'email', 'fullname',
                     'company', 'country', 'payerID']]},
        'GetAdvancedPersonalData':
            {'attributeList.attribute':
                [amo.PAYPAL_PERSONAL[k] for k in
                    ['birthDate', 'home', 'street1',
                     'street2', 'city', 'state', 'phone']]}
        }

    result = {}
    for url, data in calls.items():
        data = call(url, data)
        for k, v in data.items():
            if k.endswith('personalDataKey'):
                k_ = k.rsplit('.', 1)[0]
                v_ = amo.PAYPAL_PERSONAL_LOOKUP[v]
                # If the value isn't present the value won't be there.
                result[v_] = data.get(k_ + '.personalDataValue', '')

    return result


def check_permission(token, permissions):
    """
    Asks PayPal whether the PayPal ID for this account has granted
    the permissions requested to us. Permissions are strings from the
    PayPal documentation.
    Documentation: http://bit.ly/zlhXlT

    """
    # This is set in settings_test so we don't start calling PayPal
    # by accident. Explicitly set this in your tests.
    if not settings.PAYPAL_PERMISSIONS_URL:
        return False
    paypal_log.debug('Checking refund permission for token: %s..'
                     % token[:10])
    try:
        with statsd.timer('paypal.permissions.refund'):
            r = _call(settings.PAYPAL_PERMISSIONS_URL + 'GetPermissions',
                      {'token': token})
    except PaypalError, error:
        paypal_log.debug('Paypal returned error for token: %s.. error: %s'
                         % (token[:10], error))
        return False
    # in the future we may ask for other permissions so let's just
    # make sure REFUND is one of them.
    paypal_log.debug('Paypal returned permissions for token: %s.. perms: %s'
                     % (token[:10], r))
    result = [v for (k, v) in r.iteritems() if k.startswith('scope')]
    return set(permissions).issubset(set(result))


def get_permission_url(addon, dest, scope):
    """
    Send permissions request to PayPal for privileges on
    this PayPal account. Returns URL on PayPal site to visit.
    Documentation: http://bit.ly/zlhXlT
    """
    # This is set in settings_test so we don't start calling PayPal
    # by accident. Explicitly set this in your tests.
    if not settings.PAYPAL_PERMISSIONS_URL:
        return ''

    paypal_log.debug('Getting refund permission URL for addon: %s' % addon.pk)

    with statsd.timer('paypal.permissions.url'):
        url = urlparams(reverse('devhub.addons.acquire_refund_permission',
                                args=[addon.slug]),
                        dest=dest)
        try:
            r = _call(settings.PAYPAL_PERMISSIONS_URL + 'RequestPermissions',
                      {'scope': scope, 'callback': absolutify(url)})
        except PaypalError, e:
            paypal_log.debug('Error on refund permission URL addon: %s, %s' %
                             (addon.pk, e))
            if e.id == '580028':
                # PayPal is very picky about where they redirect users to.
                # If you try and create a PayPal permissions URL on a
                # zamboni that has a non-standard port number or a
                # non-standard TLD, it will blow up with an error. We need
                # to be able to at least visit these pages and alter them
                # in dev, so this will give you a broken token that doesn't
                # work, but at least the page will function.
                r = {'token': 'wont-work-paypal-doesnt-like-your-domain'}
            else:
                raise
    return (settings.PAYPAL_CGI_URL +
            '?cmd=_grant-permission&request_token=%s' % r['token'])


def get_permissions_token(request_token, verification_code):
    """
    Send request for permissions token, after user has granted the
    requested permissions via the PayPal page we redirected them to.
    """
    with statsd.timer('paypal.permissions.token'):
        r = _call(settings.PAYPAL_PERMISSIONS_URL + 'GetAccessToken',
                  {'token': request_token, 'verifier': verification_code})
    return r['token']


def get_preapproval_key(data):
    """
    Get a preapproval key from PayPal. If this passes, you get a key that
    you can use in a redirect to PayPal.
    """
    paypal_data = {
        'currencyCode': 'USD',
        'startingDate': data['startDate'].strftime('%Y-%m-%d'),
        'endingDate': data['endDate'].strftime('%Y-%m-%d'),
        'maxTotalAmountOfAllPayments': str(data.get('maxAmount', '2000')),
        'returnUrl': absolutify(reverse(data['pattern'], args=['complete'])),
        'cancelUrl': absolutify(reverse(data['pattern'], args=['cancel'])),
    }
    with statsd.timer('paypal.preapproval.token'):
        response = _call(settings.PAYPAL_PAY_URL + 'Preapproval', paypal_data,
                         ip=data.get('ip'))

    return response


def get_preapproval_url(key):
    """
    Returns the URL that you need to bounce user to in order to set up
    pre-approval.
    """
    return urlparams(settings.PAYPAL_CGI_URL, cmd='_ap-preapproval',
                     preapprovalkey=key)


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
    request = urllib2.Request(url)

    if 'requestEnvelope.errorLanguage' not in paypal_data:
        paypal_data['requestEnvelope.errorLanguage'] = 'en_US'

    for key, value in [
            ('security-userid', settings.PAYPAL_EMBEDDED_AUTH['USER']),
            ('security-password', settings.PAYPAL_EMBEDDED_AUTH['PASSWORD']),
            ('security-signature', settings.PAYPAL_EMBEDDED_AUTH['SIGNATURE']),
            ('application-id', settings.PAYPAL_APP_ID),
            ('request-data-format', 'NV'),
            ('response-data-format', 'NV')]:
        request.add_header('X-PAYPAL-%s' % key.upper(), value)

    if ip:
        request.add_header('X-PAYPAL-DEVICE-IPADDRESS', ip)

    # Warning, a urlencode will not work with chained payments, it must
    # be sorted and the key should not be escaped.
    opener = urllib2.build_opener()
    try:
        with socket_timeout(10):
            feeddata = opener.open(request, _nvp_dump(paypal_data)).read()
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

    response = dict(urlparse.parse_qsl(feeddata))

    if 'error(0).errorId' in response:
        id_, msg = response['error(0).errorId'], response['error(0).message']
        paypal_log.error('Paypal Error (%s): %s' % (id_, msg))
        raise errors.get(id_, PaypalError)(id=id_)

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


def paypal_log_cef(request, addon, uuid, msg, caps, longer):
    log_cef('Paypal %s' % msg, 5, request,
            username=request.amo_user,
            signature='PAYPAL%s' % caps,
            msg=longer, cs2=addon.name, cs2Label='PaypalTransaction',
            cs4=uuid, cs4Label='TxID')
