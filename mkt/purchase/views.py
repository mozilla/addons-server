import hashlib
import json
import uuid

from django import http
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
import jinja2
from tower import ugettext as _
import waffle

import amo
from amo import messages
from amo.decorators import login_required, post_required, write
from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_not_purchased)
from addons.models import Addon
from amo.utils import urlparams
from market.forms import PriceCurrencyForm
import paypal
from stats.models import Contribution


log = commonware.log.getLogger('z.purchase')
addon_view = addon_view_factory(qs=Addon.objects.valid)


@login_required
@addon_view
@can_be_purchased
@has_not_purchased
@write
@post_required
def purchase(request, addon):
    log.debug('Starting purchase of addon: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    amount = addon.premium.get_price()
    source = request.POST.get('source', '')
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()
    # L10n: {0} is the addon name.
    contrib_for = _(u'Purchase of {0}').format(jinja2.escape(addon.name))

    # Default is USD.
    amount, currency = addon.premium.get_price(), 'USD'

    # If tier is specified, then let's look it up.
    form = PriceCurrencyForm(data=request.POST, price=addon.premium.price)
    if form.is_valid():
        tier = form.get_tier()
        if tier:
            amount, currency = tier.price, tier.currency

    paykey, status, error = '', '', ''
    preapproval = None
    if waffle.flag_is_active(request, 'allow-pre-auth') and request.amo_user:
        preapproval = request.amo_user.get_preapproval()

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
        contrib = Contribution(addon_id=addon.id, amount=amount,
                               source=source, source_locale=request.LANG,
                               uuid=str(uuid_), type=amo.CONTRIB_PENDING,
                               paykey=paykey, user=request.amo_user)
        log.debug('Storing contrib for uuid: %s' % uuid_)

        # If this was a pre-approval, it's completed already, we'll
        # double check this with PayPal, just to be sure nothing went wrong.
        if status == 'COMPLETED':
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'Purchase', 'PURCHASE',
                                  'A user purchased using pre-approval')

            log.debug('Status is completed for uuid: %s' % uuid_)
            if paypal.check_purchase(paykey) == 'COMPLETED':
                log.debug('Check purchase is completed for uuid: %s' % uuid_)
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
        return redirect(url)

    messages.success(request, _('Purchase complete'))
    return redirect(addon.get_detail_url())


@login_required
@addon_view
@can_be_purchased
@write
def purchase_done(request, addon, status):
    result = ''
    if status == 'complete':
        uuid_ = request.GET.get('uuid')
        log.debug('Looking up contrib for uuid: %s' % uuid_)

        # The IPN may, or may not have come through. Which means looking for
        # a for pre or post IPN contributions. If both fail, then we've not
        # got a matching contribution.
        lookup = (Q(uuid=uuid_, type=amo.CONTRIB_PENDING) |
                  Q(transaction_id=uuid_, type=amo.CONTRIB_PURCHASE))
        con = get_object_or_404(Contribution, lookup)

        log.debug('Check purchase paypal addon: %s, user: %s, paykey: %s'
                  % (addon.pk, request.amo_user.pk, con.paykey[:10]))
        try:
            result = paypal.check_purchase(con.paykey)
            if result == 'ERROR':
                paypal.paypal_log_cef(request, addon, uuid_,
                                      'Purchase Fail', 'PURCHASEFAIL',
                                      'Checking purchase state returned error')
                raise
        except:
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'Purchase Fail', 'PURCHASEFAIL',
                                  'There was an error checking purchase state')
            log.error('Check purchase paypal addon: %s, user: %s, paykey: %s'
                      % (addon.pk, request.amo_user.pk, con.paykey[:10]),
                      exc_info=True)
            result = 'ERROR'
            status = 'error'

        log.debug('Paypal returned: %s for paykey: %s'
                  % (result, con.paykey[:10]))
        if result == 'COMPLETED' and con.type == amo.CONTRIB_PENDING:
            con.update(type=amo.CONTRIB_PURCHASE)

    context = {'realurl': request.GET.get('realurl', ''),
               'status': status, 'result': result,
               'product': addon}

    response = jingo.render(request, 'purchase/done.html', context)
    response['x-frame-options'] = 'allow'
    return response
