import calendar
import sys
import time
from urllib import urlencode
import urlparse

from django import http
from django.db.transaction import commit_on_success
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import jwt
from moz_inapp_pay.verify import verify_claims, verify_keys
import waffle

from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_not_purchased)
import amo
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from apps.market.models import PriceCurrency
from lib.crypto.bluevia import (get_uuid, InvalidSender, parse_from_bluevia,
                                sign_bluevia_jwt)
from lib.pay_server import client
from mkt.webapps.models import Webapp
from stats.models import ClientData, Contribution

from . import bluevia_tasks as tasks
from .views import start_purchase

log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Webapp.objects.valid)


def prepare_bluevia_pay(data):
    issued_at = calendar.timegm(time.gmtime())
    return sign_bluevia_jwt({
                'iss': 'marketplaceID',  # placeholder
                'typ': 'tu.com/payments/inapp/v1',
                'aud': 'tu.com',
                'iat': issued_at,
                'exp': issued_at + 3600,  # expires in 1 hour
                'request': {
                    'name': data['app_name'],
                    'description': data['app_description'],
                    'price': data['prices'],
                    'defaultPrice': data['currency'],
                    'postbackURL': data['postback_url'],
                    'chargebackURL': data['chargeback_url'],
                    'productData': data['product_data']
                }
            })


def prepare_bluevia_refund(data):
    issued_at = calendar.timegm(time.gmtime())
    return sign_bluevia_jwt({
                'iss': 'developerIdentifier',  # placeholder
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

    prices = [{'currency': cur, 'amount': str(tier.price)}
              for cur, tier in addon.premium.price.currencies()]

    data = {'amount': str(amount),
            'prices': prices, 'currency': currency,
            'app_name': unicode(addon.name),
            'app_description': unicode(addon.description),
            'postback_url': absolutify(reverse('bluevia.postback')),
            'chargeback_url': absolutify(reverse('bluevia.chargeback')),
            'seller': addon.pk,
            'product_data': urlencode({'contrib_uuid': uuid_,
                                       'addon_id': addon.pk}),
            'typ': 'tu.com/payments/inapp/v1',
            'aud': 'tu.com',
            'memo': contrib_for}

    return {'blueviaJWT': prepare_bluevia_pay(data),
            'contribStatusURL': reverse('bluevia.pay_status',
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
        data = parse_from_bluevia(signed_jwt, request.META.get('REMOTE_ADDR'))
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
    return {'blueviaJWT': prepare_bluevia_refund(data)}


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
        data = parse_from_bluevia(signed_jwt, request.META.get('REMOTE_ADDR'))
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
