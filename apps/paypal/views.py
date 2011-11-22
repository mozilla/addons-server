from decimal import Decimal
import random
import re
import urllib2

from django import http
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import phpserialize as php
from statsd import statsd

import amo
from amo.decorators import no_login_required, write
from stats.models import Contribution, ContributionError, SubscriptionEvent

paypal_log = commonware.log.getLogger('z.paypal')


@write
@csrf_exempt
@no_login_required
def paypal(request):
    """
    Handle PayPal IPN post-back for contribution transactions.

    IPN will retry periodically until it gets success (status=200). Any
    db errors or replication lag will result in an exception and http
    status of 500, which is good so PayPal will try again later.

    PayPal IPN variables available at:
    https://cms.paypal.com/us/cgi-bin/?cmd=_render-content
                    &content_ID=developer/e_howto_html_IPNandPDTVariables
    """
    try:
        return _paypal(request)
    except Exception, e:
        paypal_log.error('%s\n%s' % (e, request))
        return http.HttpResponseServerError('Unknown error.')


def _log_error_with_data(msg, post):
    """Log a message along with some of the POST info from PayPal."""

    id = random.randint(0, 99999999)
    msg = "[%s] %s (dumping data)" % (id, msg)

    paypal_log.error(msg)

    logme = {'txn_id': post.get('txn_id'),
             'txn_type': post.get('txn_type'),
             'payer_email': post.get('payer_email'),
             'receiver_email': post.get('receiver_email'),
             'payment_status': post.get('payment_status'),
             'payment_type': post.get('payment_type'),
             'mc_gross': post.get('mc_gross'),
             'item_number': post.get('item_number'),
            }

    paypal_log.error("[%s] PayPal Data: %s" % (id, logme))


def _log_unmatched(post):
    key = "%s%s:%s" % (settings.CACHE_PREFIX, 'contrib',
                       post['item_number'])
    count = cache.get(key, 0) + 1

    paypal_log.warning('Contribution not found: %s, #%s, %s'
                       % (post['item_number'], count,
                          post.get('txn_id', '')))

    if count > 10:
        msg = ("PayPal sent a transaction that we don't know "
                   "about and we're giving up on it.")
        _log_error_with_data(msg, post)
        cache.delete(key)
        return http.HttpResponse('Transaction not found; skipping.')

    cache.set(key, count, 1209600)  # This is 2 weeks.
    return http.HttpResponseServerError('Contribution not found')


number = re.compile('transaction\[(?P<number>\d+)\]\.(?P<name>\w+)')
currency = re.compile('(?P<currency>\w+) (?P<amount>[\d.,]+)')


def _parse(post):
    """
    List of (old, new) codes so we can transpose the data for
    embedded payments.
    """
    for old, new in [('payment_status', 'status'),
                     ('item_number', 'tracking_id'),
                     ('txn_id', 'tracking_id'),
                     ('payer_email', 'sender_email')]:
        if old not in post and new in post:
            post[old] = post[new]

    transactions = {}
    for k, v in post.items():
        match = number.match(k)
        if match:
            data = match.groupdict()
            transactions.setdefault(data['number'], {})
            transactions[data['number']][data['name']] = v

    return post, transactions


def _parse_currency(amount):
    """Parse USD 10.00 into a dictionary of currency and amount as Decimal."""
    res = currency.match(amount).groupdict()
    if 'amount' in res:
        res['amount'] = Decimal(res['amount'])
    return res


def _paypal(request):

    if request.method != 'POST':
        return http.HttpResponseNotAllowed(['POST'])

    # raw_post_data has to be accessed before request.POST. wtf django?
    raw, post = request.raw_post_data, request.POST.copy()
    paypal_log.info('IPN received: %s' % raw)

    # Check that the request is valid and coming from PayPal.
    # The order of the params has to match the original request.
    data = u'cmd=_notify-validate&' + raw
    with statsd.timer('paypal.validate-ipn'):
        paypal_response = urllib2.urlopen(settings.PAYPAL_CGI_URL,
                                          data, 20).readline()

    post, transactions = _parse(post)

    # If paypal doesn't like us, fail.
    if paypal_response != 'VERIFIED':
        msg = ("Expecting 'VERIFIED' from PayPal, got '%s'. "
               "Failing." % paypal_response)
        _log_error_with_data(msg, post)
        return http.HttpResponseForbidden('Invalid confirmation')

    # Cope with subscription events.
    if post.get('txn_type', '').startswith('subscr_'):
        SubscriptionEvent.objects.create(post_data=php.serialize(post))
        paypal_log.info('Subscription created: %s' % post.get('txn_id', ''))
        return http.HttpResponse('Success!')

    payment_status = post.get('payment_status', '').lower()
    if payment_status != 'completed':
        paypal_log.info('Ignoring: %s, %s' %
                        (payment_status, post.get('txn_id', '')))
        return http.HttpResponse('Payment not completed %s'
                                 % post.get('txn_id', ''))

    methods = {'refunded': paypal_refunded,
               'completed': paypal_completed,
               'reversal': paypal_reversal}

    result = None
    for key, value in transactions.items():
        status = value['status'].lower()
        result = methods[status](request, post, value)

    if not result:
        return _log_unmatched(post)

    return result


def paypal_refunded(request, post, transaction):
    try:
        original = Contribution.objects.get(transaction_id=post['txn_id'])
    except Contribution.DoesNotExist:
        return None

    # If the contribution has a related contribution we've processed it.
    try:
        original = Contribution.objects.get(related=original)
        paypal_log.info('Related contribution, state: %s, pk: %s' %
                        (original.related.type, original.related.pk))
        return http.HttpResponse('Transaction already processed')
    except Contribution.DoesNotExist:
        pass

    paypal_log.info('Refund IPN received: %s' % post['txn_id'])
    amount = _parse_currency(transaction['amount'])

    Contribution.objects.create(
        addon=original.addon, related=original,
        user=original.user, type=amo.CONTRIB_REFUND,
        amount=-amount['amount'], currency=amount['currency'],
        post_data=php.serialize(post)
    )
    paypal_log.info('Refund successfully processed')
    return http.HttpResponse('Success!')


def paypal_reversal(request, post, transaction):
    try:
        original = Contribution.objects.get(transaction_id=post['txn_id'])
    except Contribution.DoesNotExist:
        return None

    if (Contribution.objects.filter(transaction_id=post['txn_id'],
                                    type=amo.CONTRIB_CHARGEBACK)
                            .exists()):
        paypal_log.info('Reversal IPN already processed')
        return http.HttpResponse('Transaction already processed')

    paypal_log.info('Reversal IPN received: %s' % post['txn_id'])
    amount = _parse_currency(transaction['amount'])
    refund = Contribution.objects.create(
        addon=original.addon, related=original,
        user=original.user, type=amo.CONTRIB_CHARGEBACK,
        amount=-amount['amount'], currency=amount['currency'],
        post_data=php.serialize(post)
    )
    refund.mail_chargeback()
    return http.HttpResponse('Success!')


def paypal_completed(request, post, transaction):
    # Note that when this completes the uuid is moved over to transaction_id.
    try:
        original = Contribution.objects.get(uuid=post['txn_id'])
    except Contribution.DoesNotExist:
        return None

    # Make sure transaction has not yet been processed.
    if (Contribution.objects.filter(transaction_id=post['txn_id'],
                                    type=amo.CONTRIB_PURCHASE)
                            .exists()):
        paypal_log.info('Completed IPN already processed')
        return http.HttpResponse('Transaction already processed')

    paypal_log.info('Completed IPN received: %s' % post['txn_id'])
    original.transaction_id = post['txn_id']
    # Embedded payments does not send an mc_gross.
    if 'mc_gross' in post:
        original.amount = post['mc_gross']
    original.uuid = None
    original.post_data = php.serialize(post)
    original.save()

    # Send thankyou email.
    try:
        original.mail_thankyou(request)
    except ContributionError as e:
        # A failed thankyou email is not a show stopper, but is good to know.
        paypal_log.error('Thankyou note email failed with error: %s' % e)
    paypal_log.info('Completed successfully processed')
    return http.HttpResponse('Success!')
