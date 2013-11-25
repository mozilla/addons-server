import calendar
import hashlib
import sys
import time
import urlparse
import uuid
from decimal import Decimal
from urllib import urlencode

from django import http
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

import bleach
import commonware.log
from tower import ugettext as _

from addons.decorators import addon_view_factory, can_be_purchased
import amo
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from lib.cef_loggers import app_pay_cef
from lib.crypto.webpay import (InvalidSender, parse_from_webpay,
                               sign_webpay_jwt)
from mkt.api.exceptions import AlreadyPurchased
from mkt.webapps.models import Webapp
from stats.models import ClientData, Contribution

from . import webpay_tasks as tasks

log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Webapp.objects.valid)


def start_purchase(request, addon):
    log.debug('Starting purchase of app: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    amount = addon.get_price(region=request.REGION.id)
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()
    # L10n: {0} is the addon name.
    contrib_for = (_(u'Firefox Marketplace purchase of {0}')
                   .format(addon.name))

    currency = request.REGION.default_currency
    return amount, currency, uuid_, contrib_for


def make_ext_id(addon_pk):
    """
    Generates a webpay/solitude external ID for this addon's primary key.
    """
    # This namespace is currently necessary because app products
    # are mixed into an application's own in-app products.
    # Maybe we can fix that.
    # Also, we may use various dev/stage servers with the same
    # Bango test API.
    domain = getattr(settings, 'DOMAIN', None)
    if not domain:
        domain = 'marketplace-dev'
    ext_id = domain.split('.')[0]
    return '%s:%s' % (ext_id, addon_pk)


@login_required
@addon_view
@write
@post_required
@json_view
def prepare_pay(request, addon):
    return _prepare_pay(request, addon)


@can_be_purchased
def _prepare_pay(request, addon):
    """Prepare a JWT to pass into navigator.pay()"""
    if addon.is_premium() and addon.has_purchased(request.amo_user):
        log.info('Already purchased: %d' % addon.pk)
        raise AlreadyPurchased

    amount, currency, uuid_, contrib_for = start_purchase(request, addon)
    log.debug('Storing contrib for uuid: %s' % uuid_)
    Contribution.objects.create(addon_id=addon.id, amount=amount,
                                source=request.REQUEST.get('src', ''),
                                source_locale=request.LANG,
                                uuid=str(uuid_), type=amo.CONTRIB_PENDING,
                                paykey=None, user=request.amo_user,
                                price_tier=addon.premium.price,
                                client_data=ClientData.get_or_create(request))

    # Until atob() supports encoded HTML we are stripping all tags.
    # See bug 831524
    app_description = bleach.clean(unicode(addon.description), strip=True,
                                   tags=[])

    acct = addon.app_payment_account.payment_account
    seller_uuid = acct.solitude_seller.uuid
    application_size = addon.current_version.all_files[0].size
    issued_at = calendar.timegm(time.gmtime())
    icons = {}
    for size in amo.ADDON_ICON_SIZES:
        icons[str(size)] = absolutify(addon.get_icon_url(size))
    req = {
        'iss': settings.APP_PURCHASE_KEY,
        'typ': settings.APP_PURCHASE_TYP,
        'aud': settings.APP_PURCHASE_AUD,
        'iat': issued_at,
        'exp': issued_at + 3600,  # expires in 1 hour
        'request': {
            'name': unicode(addon.name),
            'description': app_description,
            'pricePoint': addon.premium.price.name,
            'id': make_ext_id(addon.pk),
            'postbackURL': absolutify(reverse('webpay.postback')),
            'chargebackURL': absolutify(reverse('webpay.chargeback')),
            'productData': urlencode({'contrib_uuid': uuid_,
                                      'seller_uuid': seller_uuid,
                                      'addon_id': addon.pk,
                                      'application_size': application_size}),
            'icons': icons,
        }
    }

    jwt_ = sign_webpay_jwt(req)
    log.debug('Preparing webpay JWT for addon %s: %s' % (addon, jwt_))
    app_pay_cef.log(request, 'Preparing JWT', 'preparing_jwt',
                    'Preparing JWT for: %s' % (addon.pk), severity=3)

    if request.API:
        url = reverse('webpay-status', kwargs={'uuid': uuid_})
    else:
        url = reverse('webpay.pay_status', args=[addon.app_slug, uuid_])
    return {'webpayJWT': jwt_, 'contribStatusURL': url}


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
    """Verify signature and set contribution to paid."""
    signed_jwt = request.POST.get('notice', '')
    try:
        data = parse_from_webpay(signed_jwt, request.META.get('REMOTE_ADDR'))
    except InvalidSender, exc:
        app_pay_cef.log(request, 'Unknown app', 'invalid_postback',
                        'Ignoring invalid JWT %r: %s' % (signed_jwt, exc),
                        severity=4)
        return http.HttpResponseBadRequest()

    pd = urlparse.parse_qs(data['request']['productData'])
    contrib_uuid = pd['contrib_uuid'][0]
    try:
        contrib = Contribution.objects.get(uuid=contrib_uuid)
    except Contribution.DoesNotExist:
        etype, val, tb = sys.exc_info()
        raise LookupError('JWT (iss:%s, aud:%s) for trans_id %s '
                          'links to contrib %s which doesn\'t exist'
                          % (data['iss'], data['aud'],
                             data['response']['transactionID'],
                             contrib_uuid)), None, tb

    trans_id = data['response']['transactionID']

    if contrib.transaction_id is not None:
        if contrib.transaction_id == trans_id:
            app_pay_cef.log(request, 'Repeat postback', 'repeat_postback',
                            'Postback sent again for: %s' % (contrib.addon.pk),
                            severity=4)
            return http.HttpResponse(trans_id)
        else:
            app_pay_cef.log(request, 'Repeat postback with new trans_id',
                            'repeat_postback_new_trans_id',
                            'Postback sent again for: %s, but with new '
                            'trans_id: %s' % (contrib.addon.pk, trans_id),
                            severity=7)
            raise LookupError('JWT (iss:%s, aud:%s) for trans_id %s is for '
                              'contrib %s that is already paid and has '
                              'existing differnet trans_id: %s'
                              % (data['iss'], data['aud'],
                                 data['response']['transactionID'],
                                 contrib_uuid, contrib.transaction_id))

    log.info('webpay postback: fulfilling purchase for contrib %s with '
             'transaction %s' % (contrib, trans_id))
    app_pay_cef.log(request, 'Purchase complete', 'purchase_complete',
                    'Purchase complete for: %s' % (contrib.addon.pk),
                    severity=3)
    contrib.update(transaction_id=trans_id, type=amo.CONTRIB_PURCHASE,
                   amount=Decimal(data['response']['price']['amount']),
                   currency=data['response']['price']['currency'])

    tasks.send_purchase_receipt.delay(contrib.pk)
    return http.HttpResponse(trans_id)


@csrf_exempt
@write
@post_required
def chargeback(request):
    """
    Verify signature from and create a refund contribution tied
    to the original transaction.
    """
    raise NotImplementedError
