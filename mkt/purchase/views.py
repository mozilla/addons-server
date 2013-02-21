import hashlib
import json
import uuid

from django import http
from django.conf import settings

import commonware.log
from tower import ugettext as _
import waffle

import amo
from amo import messages
from amo.decorators import login_required, post_required, write
from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_not_purchased)
from lib.pay_server import client
from market.forms import PriceCurrencyForm
from market.models import AddonPurchase
from mkt.webapps.models import Webapp
import paypal
from stats.models import ClientData, Contribution

log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Webapp.objects.valid)


def start_purchase(request, addon):
    log.debug('Starting purchase of addon: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    amount = addon.premium.get_price()
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()
    # L10n: {0} is the addon name.
    contrib_for = (_(u'Firefox Marketplace purchase of {0}')
                   .format(addon.name))

    amount, currency = (addon.premium.get_price(),
                        request.REGION.default_currency)

    # If tier is specified, then let's look it up.
    if waffle.switch_is_active('currencies'):
        form = PriceCurrencyForm(data=request.POST, addon=addon)
        if form.is_valid():
            tier = form.get_tier()
            if tier:
                amount, currency = tier.price, tier.currency

    return amount, currency, uuid_, contrib_for


@login_required
@addon_view
@can_be_purchased
@has_not_purchased
@write
@post_required
def purchase(request, addon):
    amount, currency, uuid_, contrib_for = start_purchase(request, addon)

    if not amount:
        # We won't write a contribution row for this because there
        # will not be a valid Paypal transaction. But we have to write the
        # Purchase row, something that writing to the contribution normally
        # does for us.
        AddonPurchase.objects.safer_get_or_create(addon=addon,
                                                  user=request.amo_user)
        return http.HttpResponse(json.dumps({'url': '', 'paykey': '',
                                             'error': '',
                                             'status': 'COMPLETED'}),
                                 content_type='application/json')

    paykey, status, error = '', '', ''

    # TODO(solitude): remove this, pre-approval and currency will be
    # stored in solitude.
    preapproval = None
    if (not waffle.flag_is_active(request, 'solitude-payments')
        and request.amo_user):
        preapproval = request.amo_user.get_preapproval()
        # User the users default currency.
        if currency == 'USD' and preapproval and preapproval.currency:
            currency = preapproval.currency

    if waffle.flag_is_active(request, 'solitude-payments'):
        # Now call the client.
        result = {}
        try:
            result = client.pay({'amount': amount, 'currency': currency,
                                 'buyer': request.amo_user, 'seller': addon,
                                 'memo': contrib_for})
        except client.Error as error:
            # Note that by assigning this to error, it will go into the return
            # value for the json. General solitude errors will then be
            # reported back to the user.
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'PayKey Failure', 'PAYKEYFAIL',
                                  'There was an error getting the paykey')
            log.error('Error getting paykey: %s' % addon.pk, exc_info=True)

        # TODO(solitude): just use the dictionary when solitude is live.
        paykey = result.get('pay_key', '')
        status = result.get('status', '')
        uuid_ = result.get('uuid', '')

    else:
        # TODO(solitude): remove this when solitude goes live.
        try:
            paykey, status = paypal.get_paykey(dict(
                amount=amount,
                chains=settings.PAYPAL_CHAINS,
                currency=currency,
                email=addon.paypal_id,
                ip=request.META.get('REMOTE_ADDR'),
                memo=contrib_for,
                pattern='purchase.done',
                preapproval=preapproval,
                qs={'realurl': request.POST.get('realurl')},
                slug=addon.app_slug,
                uuid=uuid_
            ))
        except paypal.PaypalError as error:
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'PayKey Failure', 'PAYKEYFAIL',
                                  'There was an error getting the paykey')
            log.error('Error getting paykey, purchase of addon: %s' % addon.pk,
                      exc_info=True)

    if paykey:
        # TODO(solitude): at some point we'll have to see what to do with
        # contributions.
        download_source = request.REQUEST.get('src', '')
        contrib = Contribution(addon_id=addon.id, amount=amount,
                               source=download_source,
                               source_locale=request.LANG,
                               uuid=str(uuid_), type=amo.CONTRIB_PENDING,
                               paykey=paykey, user=request.amo_user,
                               price_tier=addon.premium.price,
                               client_data=ClientData.get_or_create(request))

        log.debug('Storing contrib for uuid: %s' % uuid_)

        # If this was a pre-approval, it's completed already, we'll
        # double check this with PayPal, just to be sure nothing went wrong.
        if status == 'COMPLETED':
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'Purchase', 'PURCHASE',
                                  'A user purchased using pre-approval')

            log.debug('Status completed for uuid: %s' % uuid_)
            if waffle.flag_is_active(request, 'solitude-payments'):
                result = client.post_pay_check(data={'pay_key': paykey})
                if result['status'] == 'COMPLETED':
                    contrib.type = amo.CONTRIB_PURCHASE
                else:
                    log.error('Check purchase failed on uuid: %s' % uuid_)
                    status = 'NOT-COMPLETED'

            else:
                #TODO(solitude): remove this when solitude goes live.
                if paypal.check_purchase(paykey) == 'COMPLETED':
                    log.debug('Check purchase completed for uuid: %s' % uuid_)
                    contrib.type = amo.CONTRIB_PURCHASE
                else:
                    # In this case PayPal disagreed, we should not be trusting
                    # what get_paykey said. Which is a worry.
                    log.error('Check purchase failed on uuid: %s' % uuid_)
                    status = 'NOT-COMPLETED'

        contrib.save()

    else:
        log.error('No paykey present for uuid: %s' % uuid_)

    log.debug('Got paykey for addon: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    url = '%s?paykey=%s' % (settings.PAYPAL_FLOW_URL, paykey)
    if request.POST.get('result_type') == 'json' or request.is_ajax():
        return http.HttpResponse(json.dumps({'url': url,
                                             'paykey': paykey,
                                             'error': str(error),
                                             'status': status}),
                                 content_type='application/json')

    # This is the non-Ajax fallback.
    if status != 'COMPLETED':
        return http.HttpResponseRedirect(url)

    messages.success(request, _('Purchase complete'))
    return http.HttpResponseRedirect(addon.get_detail_url())


@post_required
@login_required
@addon_view
def preapproval(request, addon):
    # This should be deleted, but for the moment lets fix import loop.
    from mkt.account.views import preapproval as user_preapproval
    return user_preapproval(request, complete=addon.get_detail_url(),
                            cancel=addon.get_detail_url())
