import sys
from urllib import urlencode
import urlparse

from django import http
from django.views.decorators.csrf import csrf_exempt

import commonware.log
import jwt
from moz_inapp_pay.verify import verify_claims, verify_keys

from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_not_purchased)
import amo
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from lib.pay_server import client
from mkt.webapps.models import Webapp
from stats.models import ClientData, Contribution

from . import bluevia_tasks as tasks
from .views import start_purchase

log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Webapp.objects.valid)


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
    data = {'amount': amount, 'currency': currency,
            'app_name': unicode(addon.name),
            'app_description': unicode(addon.description),
            'postback_url': absolutify(reverse('bluevia.postback')),
            'chargeback_url': absolutify(reverse('bluevia.chargeback')),
            'seller': addon.pk,
            'product_data': urlencode({'contrib_uuid': uuid_,
                                       'addon_id': addon.pk}),
            'memo': contrib_for}

    return {'bluevia_jwt': client.prepare_bluevia_pay(data),
            'contrib_uuid': uuid_}


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
    signed_jwt = request.read()  # request.raw_post_data fails tests randomly
    result = client.verify_bluevia_jwt(signed_jwt)
    if not result['valid']:
        ip = (request.META.get('HTTP_X_FORWARDED_FOR', '') or
              request.META.get('REMOTE_ADDR', ''))
        if not ip:
            ip = '(unknown)'
        log.info('Received invalid bluevia postback from IP %s' % ip)
        return http.HttpResponseBadRequest('invalid request')
    # From here on, let all exceptions raise. The JWT comes from BlueVia
    # so if anything fails we want to know ASAP.
    data = jwt.decode(signed_jwt, verify=False)
    verify_claims(data)
    iss, aud, product_data, trans_id = verify_keys(data,
                                            ('iss',
                                             'aud',
                                             'request.productData',
                                             'response.transactionID'))
    log.info('received BlueVia postback JWT: iss:%s aud:%s '
             'trans_id:%s product_data:%s'
             % (iss, aud, trans_id, product_data))
    pd = urlparse.parse_qs(product_data)
    contrib_uuid = pd['contrib_uuid'][0]
    try:
        contrib = Contribution.objects.get(uuid=contrib_uuid)
    except Contribution.DoesNotExist:
        etype, val, tb = sys.exc_info()
        raise LookupError('BlueVia JWT (iss:%s, aud:%s) for trans_id %s '
                          'links to contrib %s which doesn\'t exist'
                          % (iss, aud, trans_id, contrib_uuid)), None, tb
    contrib.update(type=amo.CONTRIB_PURCHASE,
                   bluevia_transaction_id=trans_id)

    tasks.purchase_notify.delay(signed_jwt, contrib.pk)
    return http.HttpResponse(trans_id)


@csrf_exempt
@post_required
def chargeback(request):
    """
    Verify signature from BlueVia, process refund, and notify dev chargeback.
    """
    # TODO(Kumar) bug 777007
