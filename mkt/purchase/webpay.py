import calendar
import sys
import time
from urllib import urlencode
import urlparse

from django import http
from django.conf import settings
from django.db.transaction import commit_on_success
from django.views.decorators.csrf import csrf_exempt

import commonware.log

from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_not_purchased)
import amo
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from lib.crypto.webpay import (get_uuid, InvalidSender, parse_from_webpay,
                                sign_webpay_jwt)
from mkt.webapps.models import Webapp
from stats.models import ClientData, Contribution

from . import webpay_tasks as tasks
from .views import start_purchase

log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Webapp.objects.valid)


def make_ext_id(addon_pk):
    """
    Generates a webpay/solitude external ID for this addon's primary key.
    """
    # This namespace is currently necessary because app products
    # are mixed into an application's own in-app products.
    # Maybe we can fix that.
    return 'marketplace:%s' % addon_pk


def prepare_webpay_pay(data):
    issued_at = calendar.timegm(time.gmtime())
    req = {
        'iss': settings.APP_PURCHASE_KEY,
        'typ': settings.APP_PURCHASE_TYP,
        'aud': settings.APP_PURCHASE_AUD,
        'iat': issued_at,
        'exp': issued_at + 3600,  # expires in 1 hour
        'request': {
            'name': data['app_name'],
            'description': data['app_description'],
            'pricePoint': data['price_point'],
            'id': make_ext_id(data['id']),
            'postbackURL': data['postback_url'],
            'chargebackURL': data['chargeback_url'],
            'productData': data['product_data']
        }
    }
    return sign_webpay_jwt(req)


def prepare_webpay_refund(data):
    issued_at = calendar.timegm(time.gmtime())
    return sign_webpay_jwt({
                'iss': settings.APP_PURCHASE_KEY,
                'typ': 'tu.com/payments/v1/refund',
                'aud': 'tu.com',
                'iat': issued_at,
                'exp': issued_at + 3600,  # expires in 1 hour
                'request': {
                    'refund': data['id'],
                    'reason': 'refund'
                }
            })


@login_required
@addon_view
@can_be_purchased
@has_not_purchased
@write
@post_required
@json_view
def prepare_pay(request, addon):
    """Prepare a BlueVia JWT to pass into navigator.pay()"""
    amount, currency, uuid_, contrib_for = start_purchase(request, addon)
    log.debug('Storing contrib for uuid: %s' % uuid_)
    Contribution.objects.create(addon_id=addon.id, amount=amount,
                                source=request.REQUEST.get('src', ''),
                                source_locale=request.LANG,
                                uuid=str(uuid_), type=amo.CONTRIB_PENDING,
                                paykey=None, user=request.amo_user,
                                price_tier=addon.premium.price,
                                client_data=ClientData.get_or_create(request))

    acct = addon.app_payment_account.payment_account
    seller_uuid = acct.solitude_seller.uuid
    data = {'amount': str(amount),
            'price_point': addon.premium.price.pk,
            'id': addon.pk,
            'app_name': unicode(addon.name),
            'app_description': unicode(addon.description),
            'postback_url': absolutify(reverse('webpay.postback')),
            'chargeback_url': absolutify(reverse('webpay.chargeback')),
            'seller': addon.pk,
            'product_data': urlencode({'contrib_uuid': uuid_,
                                       'seller_uuid': seller_uuid,
                                       'addon_id': addon.pk}),
            'typ': 'tu.com/payments/inapp/v1',
            'aud': 'tu.com',
            'memo': contrib_for}

    return {'webpayJWT': prepare_webpay_pay(data),
            'contribStatusURL': reverse('webpay.pay_status',
                                        args=[addon.app_slug, uuid_])}


@login_required
@addon_view
@write
@json_view
def pay_status(request, addon, contrib_uuid):
    """
    Return JSON dict of {status: complete|incomplete}.

    The status of the payment is only complete when it exists by uuid,
    was purchased by the logged in user, and has been marked paid by the
    JWT postback. After that the UI is free to call app/purchase/record
    to generate a receipt.
    """
    au = request.amo_user
    qs = Contribution.objects.filter(uuid=contrib_uuid,
                                     addon__addonpurchase__user=au,
                                     type=amo.CONTRIB_PURCHASE)
    return {'status': 'complete' if qs.exists() else 'incomplete'}


@csrf_exempt
@write
@post_required
def postback(request):
    """Verify signature from BlueVia and set contribution to paid."""
    signed_jwt = request.raw_post_data
    try:
        data = parse_from_webpay(signed_jwt, request.META.get('REMOTE_ADDR'))
    except InvalidSender:
        return http.HttpResponseBadRequest()

    pd = urlparse.parse_qs(data['request']['productData'])
    contrib_uuid = pd['contrib_uuid'][0]
    try:
        contrib = Contribution.objects.get(uuid=contrib_uuid)
    except Contribution.DoesNotExist:
        etype, val, tb = sys.exc_info()
        raise LookupError('BlueVia JWT (iss:%s, aud:%s) for trans_id %s '
                          'links to contrib %s which doesn\'t exist'
                          % (data['iss'], data['aud'],
                             data['response']['transactionID'],
                             contrib_uuid)), None, tb

    contrib.update(type=amo.CONTRIB_PURCHASE,
                   bluevia_transaction_id=data['response']['transactionID'])

    tasks.purchase_notify.delay(signed_jwt, contrib.pk)
    return http.HttpResponse(data['response']['transactionID'])


@addon_view
@post_required
@login_required
@json_view
@write
@commit_on_success
def prepare_refund(request, addon, uuid):
    """
    Prepare a BlueVia JWT to pass into navigator.pay()
    for a specific transaction.
    """
    try:
        # Looks up the contribution based upon the BlueVia transaction id.
        to_refund = Contribution.objects.get(user=request.amo_user,
                                             bluevia_transaction_id=uuid,
                                             addon=addon)
    except Contribution.DoesNotExist:
        log.info('Not found: %s, %s' % (request.amo_user.pk, uuid))
        return http.HttpResponseBadRequest()

    # The refund must be within 30 minutes, give or take and the transaction
    # must not already be refunded.
    if to_refund.type != amo.CONTRIB_PURCHASE:
        log.info('Not a purchase: %s' % uuid)
        return http.HttpResponseBadRequest()

    if not to_refund.is_instant_refund(period=30 * 60 + 10):
        log.info('Over 30 minutes ago: %s' % uuid)
        return http.HttpResponseBadRequest()

    if to_refund.is_refunded():
        log.info('Already refunded: %s' % uuid)
        return http.HttpResponseBadRequest()

    data = {'id': to_refund.bluevia_transaction_id}
    return {'webpayJWT': prepare_webpay_refund(data)}


@csrf_exempt
@write
@post_required
def chargeback(request):
    """
    Verify signature from BlueVia and create a refund contribution tied
    to the original transaction.
    """
    signed_jwt = request.read()
    # Check the JWT we've got is valid.
    try:
        data = parse_from_webpay(signed_jwt, request.META.get('REMOTE_ADDR'))
    except InvalidSender:
        return http.HttpResponseBadRequest()

    uuid = data['response']['transactionID']
    # Check that we've got a valid uuid.
    # Looks up the contribution based upon the BlueVia transaction id.
    try:
        original = Contribution.objects.get(bluevia_transaction_id=uuid)
    except Contribution.DoesNotExist:
        log.info('Not found: %s' % uuid)
        return http.HttpResponseBadRequest()

    # Create a refund in our end.
    Contribution.objects.create(addon_id=original.addon_id,
        amount=-original.amount, currency=original.currency, paykey=None,
        price_tier_id=original.price_tier_id, related=original,
        source=request.REQUEST.get('src', ''), source_locale=request.LANG,
        type=amo.CONTRIB_REFUND, user_id=original.user_id, uuid=get_uuid())

    tasks.chargeback_notify.delay(signed_jwt, original.pk)
    return http.HttpResponse(uuid)
