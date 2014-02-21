import random
import re
from decimal import Decimal

from django import http
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import phpserialize as php
import requests
from django_statsd.clients import statsd

import amo
from amo.decorators import post_required, write
from paypal import paypal_log_cef
from stats.db import StatsDictField
from stats.models import Contribution, ContributionError


paypal_log = commonware.log.getLogger('z.paypal')


@write
@csrf_exempt
@post_required
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
        paypal_log.error('%s\n%s' % (e, request), exc_info=True)
        if settings.IN_TEST_SUITE:
            raise
        return http.HttpResponseServerError('Unknown error.')


# TODO(solitude): alot of this can be removed or refactored.
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


def _parse_currency(value):
    """Parse USD 10.00 into a dictionary of currency and amount as Decimal."""
    # If you are using solitude, it's a dictionary. However it returns
    # amount as a string, not a decimal.
    if not isinstance(value, dict):
        value = currency.match(value).groupdict()
    value['amount'] = Decimal(value['amount'])
    return value


def _paypal(request):
    # Must be this way around.
    post, raw = request.POST.copy(), request.read()
    paypal_log.info('IPN received: %s' % raw)

    # Check that the request is valid and coming from PayPal.
    # The order of the params has to match the original request.
    data = u'cmd=_notify-validate&' + raw
    with statsd.timer('paypal.validate-ipn'):
        paypal_response = requests.post(settings.PAYPAL_CGI_URL, data,
                                        verify=True,
                                        cert=settings.PAYPAL_CERT)

    post, transactions = _parse(post)

    # If paypal doesn't like us, fail.
    if paypal_response.text != 'VERIFIED':
        msg = ("Expecting 'VERIFIED' from PayPal, got '%s'. "
               "Failing." % paypal_response)
        _log_error_with_data(msg, post)
        return http.HttpResponseForbidden('Invalid confirmation')

    payment_status = post.get('payment_status', '').lower()
    if payment_status != 'completed':
        paypal_log.info('Payment status not completed: %s, %s'
                        % (post.get('txn_id', ''), payment_status))
        return http.HttpResponse('Ignoring %s' % post.get('txn_id', ''))

    # There could be multiple transactions on the IPN. This will deal
    # with them appropriately or cope if we don't know how to deal with
    # any of them.
    methods = {'refunded': paypal_refunded,
               'completed': paypal_completed,
               'reversal': paypal_reversal}
    result = None
    called = False
    # Ensure that we process 0, then 1 etc.
    for (k, v) in sorted(transactions.items()):
        status = v.get('status', '').lower()
        if status not in methods:
            paypal_log.info('Unknown status: %s' % status)
            continue
        result = methods[status](request, post.get('txn_id'),
                                 post, v.get('amount'))
        called = True
        # Because of chained payments a refund is more than one transaction.
        # But from our point of view, it's actually only one transaction and
        # we can safely ignore the rest.
        if result.content == 'Success!' and status == 'refunded':
            break

    if not called:
        # Whilst the payment status was completed, it contained
        # no transactions with status, which means we don't know
        # how to process it. Hence it's being ignored.
        paypal_log.info('No methods to call on: %s' % post.get('txn_id', ''))
        return http.HttpResponse('Ignoring %s' % post.get('txn_id', ''))

    return result


def paypal_refunded(request, transaction_id, serialize=None, amount=None):
    try:
        original = Contribution.objects.get(transaction_id=transaction_id)
    except Contribution.DoesNotExist:
        paypal_log.info('Ignoring transaction: %s' % transaction_id)
        return http.HttpResponse('Transaction not found; skipping.')

    # If the contribution has a related contribution we've processed it.
    try:
        original = Contribution.objects.get(related=original)
        paypal_log.info('Related contribution, state: %s, pk: %s' %
                        (original.related.type, original.related.pk))
        return http.HttpResponse('Transaction already processed')
    except Contribution.DoesNotExist:
        pass

    original.handle_chargeback('refund')
    paypal_log.info('Refund IPN received: %s' % transaction_id)
    price_currency = _parse_currency(amount)
    amount = price_currency['amount']
    currency = price_currency['currency']

    # Contribution with negative amount for refunds.
    Contribution.objects.create(
        addon=original.addon, related=original,
        user=original.user, type=amo.CONTRIB_REFUND,
        amount=-amount, currency=currency,
        price_tier=original.price_tier,
        post_data=php.serialize(serialize)
    )
    paypal_log.info('Refund successfully processed')

    paypal_log_cef(request, original.addon, transaction_id,
                   'Refund', 'REFUND',
                   'A paypal refund was processed')

    return http.HttpResponse('Success!')


def paypal_reversal(request, transaction_id, serialize=None, amount=None):
    try:
        original = Contribution.objects.get(transaction_id=transaction_id)
    except Contribution.DoesNotExist:
        paypal_log.info('Ignoring transaction: %s' % transaction_id)
        return http.HttpResponse('Transaction not found; skipping.')

    # If the contribution has a related contribution we've processed it.
    try:
        original = Contribution.objects.get(related=original)
        paypal_log.info('Related contribution, state: %s, pk: %s' %
                        (original.related.type, original.related.pk))
        return http.HttpResponse('Transaction already processed')
    except Contribution.DoesNotExist:
        pass

    original.handle_chargeback('reversal')
    paypal_log.info('Reversal IPN received: %s' % transaction_id)
    amount = _parse_currency(amount)
    refund = Contribution.objects.create(
        addon=original.addon, related=original,
        user=original.user, type=amo.CONTRIB_CHARGEBACK,
        amount=-amount['amount'], currency=amount['currency'],
        post_data=php.serialize(serialize)
    )
    refund.mail_chargeback()

    paypal_log_cef(request, original.addon, transaction_id,
                   'Chargeback', 'CHARGEBACK',
                   'A paypal chargeback was processed')

    return http.HttpResponse('Success!')


def paypal_completed(request, transaction_id, serialize=None, amount=None):
    # Make sure transaction has not yet been processed.
    if Contribution.objects.filter(transaction_id=transaction_id).exists():
        paypal_log.info('Completed IPN already processed')
        return http.HttpResponse('Transaction already processed')

    # Note that when this completes the uuid is moved over to transaction_id.
    try:
        original = Contribution.objects.get(uuid=transaction_id)
    except Contribution.DoesNotExist:
        paypal_log.info('Ignoring transaction: %s' % transaction_id)
        return http.HttpResponse('Transaction not found; skipping.')

    paypal_log.info('Completed IPN received: %s' % transaction_id)
    data = StatsDictField().to_python(php.serialize(serialize))
    update = {'transaction_id': transaction_id,
              'uuid': None, 'post_data': data}

    if original.type == amo.CONTRIB_PENDING:
        # This is a purchase that has failed to hit the completed page.
        # But this ok, this IPN means that it all went through.
        update['type'] = amo.CONTRIB_PURCHASE
        # If they failed to hit the completed page, they also failed
        # to get it logged properly. This will add the log in.
        amo.log(amo.LOG.PURCHASE_ADDON, original.addon)

    if amount:
        update['amount'] = _parse_currency(amount)['amount']

    original.update(**update)
    # Send thankyou email.
    try:
        original.mail_thankyou(request)
    except ContributionError as e:
        # A failed thankyou email is not a show stopper, but is good to know.
        paypal_log.error('Thankyou note email failed with error: %s' % e)

    paypal_log_cef(request, original.addon, transaction_id,
                   'Purchase', 'PURCHASE',
                   'A user purchased or contributed to an addon')
    paypal_log.info('Completed successfully processed')
    return http.HttpResponse('Success!')
