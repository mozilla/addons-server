import hashlib
import uuid

import commonware.log
import jingo
from session_csrf import anonymous_csrf
from tower import ugettext as _
import waffle
from waffle.decorators import waffle_switch

from django import http
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404

import amo
from amo.decorators import login_required, post_required, write
from amo.urlresolvers import reverse
from lib.cef_loggers import inapp_cef
from lib.pay_server import client
from market.models import Price
import paypal
from stats.models import Contribution

from .decorators import require_inapp_request
from .helpers import render_error
from .models import InappPayment, InappPayLog, InappConfig
from . import tasks


log = commonware.log.getLogger('z.inapp_pay')


@anonymous_csrf
@waffle_switch('in-app-payments-ui')
def lobby(request):
    return jingo.render(request, 'inapp_pay/lobby.html')


@require_inapp_request
@anonymous_csrf
@write
@waffle_switch('in-app-payments-ui')
def pay_start(request, signed_req, pay_req):
    cfg = pay_req['_config']
    pr = None
    has_preapproval = False
    if request.amo_user:
        pr = request.amo_user.get_preapproval()
        has_preapproval = request.amo_user.has_preapproval_key()
    tier, price, currency = _get_price(pay_req, preapproval=pr)
    webapp = cfg.addon
    InappPayLog.log(request, 'PAY_START', config=cfg)
    tasks.fetch_product_image.delay(cfg.pk,
                                    _serializable_req(pay_req))
    data = dict(price=price,
                product=webapp,
                currency=currency,
                item=pay_req['request']['name'],
                img=cfg.image_url(pay_req['request'].get('imageURL')),
                description=pay_req['request']['description'],
                signed_request=signed_req)

    if not request.user.is_authenticated():
        return jingo.render(request, 'inapp_pay/login.html', data)
    if not has_preapproval:
        return jingo.render(request, 'inapp_pay/nowallet.html', data)
    return jingo.render(request, 'inapp_pay/pay_start.html', data)


def preauth(request):
    from mkt.account.views import preapproval
    return preapproval(request)


@require_inapp_request
@login_required
@post_required
@write
@waffle_switch('in-app-payments-ui')
def pay(request, signed_req, pay_req):
    paykey, status = '', ''
    preapproval = None
    if request.amo_user:
        preapproval = request.amo_user.get_preapproval()
    tier, price, currency = _get_price(pay_req, preapproval=preapproval)

    source = request.POST.get('source', '')
    product = pay_req['_config'].addon
    # L10n: {0} is the product name. {1} is the application name.
    contrib_for = (_(u'Firefox Marketplace in-app payment for {0} to {1}')
                   .format(pay_req['request']['name'], product.name))
    # TODO(solitude): solitude lib will create these for us.
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()

    if waffle.flag_is_active(request, 'solitude-payments'):
        # TODO(solitude): when the migration of data is completed, we
        # will be able to remove this. Seller data is populated in solitude
        # on submission or devhub changes. If those don't occur, you won't be
        # able to sell at all.
        client.create_seller_for_pay(product)

        complete = reverse('inapp_pay.pay_status',
                           args=[pay_req['_config'].pk, 'complete'])
        cancel = reverse('inapp_pay.pay_status',
                         args=[pay_req['_config'].pk, 'cancel'])

        # TODO(bug 748137): remove retry is False.
        try:
            result = client.pay({'amount': price, 'currency': currency,
                                 'buyer': request.amo_user, 'seller': product,
                                 'memo': contrib_for, 'complete': complete,
                                 'cancel': cancel}, retry=False)
        except client.Error as exc:
            paypal.paypal_log_cef(request, product, uuid_,
                                  'in-app PayKey Failure', 'PAYKEYFAIL',
                                  'There was an error getting the paykey')
            log.error(u'Error getting paykey, in-app payment: %s'
                      % pay_req['_config'].pk,
                      exc_info=True)
            InappPayLog.log(request, 'PAY_ERROR', config=pay_req['_config'])
            return render_error(request, exc)

        #TODO(solitude): just use the dictionary when solitude is live.
        paykey = result.get('pay_key', '')
        status = result.get('status', '')
        uuid_ = result.get('uuid', '')

    else:
        try:
            paykey, status = paypal.get_paykey(dict(
                amount=price,
                chains=settings.PAYPAL_CHAINS,
                currency=currency,
                email=product.paypal_id,
                ip=request.META.get('REMOTE_ADDR'),
                memo=contrib_for,
                pattern='inapp_pay.pay_status',
                preapproval=preapproval,
                qs={'realurl': request.POST.get('realurl')},
                slug=pay_req['_config'].pk,  # passed to pay_done()
                                             # via reverse()
                uuid=uuid_
            ))
        except paypal.PaypalError, exc:
            paypal.paypal_log_cef(request, product, uuid_,
                                  'in-app PayKey Failure', 'PAYKEYFAIL',
                                  'There was an error getting the paykey')
            log.error(u'Error getting paykey, in-app payment: %s'
                      % pay_req['_config'].pk,
                      exc_info=True)
            InappPayLog.log(request, 'PAY_ERROR', config=pay_req['_config'])
            return render_error(request, exc)

    with transaction.commit_on_success():
        contrib = Contribution(addon_id=product.id, amount=price,
                               source=source, source_locale=request.LANG,
                               currency=currency, uuid=str(uuid_),
                               price_tier=tier,
                               type=amo.CONTRIB_INAPP_PENDING,
                               paykey=paykey, user=request.amo_user)
        log.debug('Storing in-app payment contrib for uuid: %s' % uuid_)

        # If this was a pre-approval, it's completed already, we'll
        # double check this with PayPal, just to be sure nothing went wrong.
        if status == 'COMPLETED':
            paypal.paypal_log_cef(request, product, uuid_,
                                  'Purchase', 'PURCHASE',
                                  'A user purchased using pre-approval')

            log.debug('Status is completed for uuid: %s' % uuid_)
            if waffle.flag_is_active(request, 'solitude-payments'):
                result = client.post_pay_check(data={'pay_key': paykey})
                if result['status'] == 'COMPLETED':
                    log.debug('Check in-app payment is completed for uuid: %s'
                          % uuid_)
                    contrib.type = amo.CONTRIB_INAPP
                else:
                    # In this case PayPal disagreed, we should not be trusting
                    # what get_paykey said. Which is a worry.
                    log.error('Check in-app payment failed on uuid: %s'
                              % uuid_)
                    status = 'NOT-COMPLETED'
            else:
                # TODO(solitude): remove this when solitude goes live.
                if paypal.check_purchase(paykey) == 'COMPLETED':
                    log.debug('Check in-app payment is completed for uuid: %s'
                              % uuid_)
                    contrib.type = amo.CONTRIB_INAPP
                else:
                    # In this case PayPal disagreed, we should not be trusting
                    # what get_paykey said. Which is a worry.
                    log.error('Check in-app payment failed on uuid: %s'
                              % uuid_)
                    status = 'NOT-COMPLETED'

        contrib.save()

        payment = InappPayment.objects.create(
                                config=pay_req['_config'],
                                contribution=contrib,
                                name=pay_req['request']['name'],
                                description=pay_req['request']['description'],
                                app_data=pay_req['request']['productdata'])

        InappPayLog.log(request, 'PAY', config=pay_req['_config'])

    url = '%s?paykey=%s' % (settings.PAYPAL_FLOW_URL, paykey)

    if status != 'COMPLETED':
        return http.HttpResponseRedirect(url)

    # Payment was completed using pre-auth. Woo!
    _payment_done(request, payment)

    cfg = pay_req['_config']

    c = dict(price=price,
             product=cfg.addon,
             currency=currency,
             item=pay_req['request']['name'],
             img=cfg.image_url(pay_req['request'].get('imageURL')),
             description=pay_req['request']['description'],
             signed_request=signed_req)
    return jingo.render(request, 'inapp_pay/complete.html', c)


@anonymous_csrf
@login_required
@write
@waffle_switch('in-app-payments-ui')
def pay_status(request, config_pk, status):
    tpl_path = 'inapp_pay/'
    with transaction.commit_on_success():
        cfg = get_object_or_404(InappConfig, pk=config_pk)
        uuid_ = None
        try:
            uuid_ = str(request.GET['uuid'])
            cnt = Contribution.objects.get(uuid=uuid_)
        except (KeyError, UnicodeEncodeError, ValueError,
                Contribution.DoesNotExist), exc:
            log.error('PayPal returned invalid uuid %r from in-app payment'
                      % uuid_, exc_info=True)
            inapp_cef.log(request, cfg.addon, 'inapp_pay_status',
                          'PayPal or someone sent invalid uuid %r for '
                          'in-app pay config %r; exception: %s: %s'
                          % (uuid_, cfg.pk, exc.__class__.__name__, exc),
                          severity=4)
            return render_error(request, exc)
        payment = InappPayment.objects.get(config=cfg, contribution=cnt)
        if status == 'complete':
            cnt.update(type=amo.CONTRIB_INAPP)
            tpl = tpl_path + 'complete.html'
            action = 'PAY_COMPLETE'
        elif status == 'cancel':
            tpl = tpl_path + 'payment_cancel.html'
            action = 'PAY_CANCEL'
        else:
            raise ValueError('Unexpected status: %r' % status)

    _payment_done(request, payment, action=action)

    return jingo.render(request, tpl, {'product': cnt.addon})


def _get_price(pay_request, preapproval=None):
    """
    Get (tier, price, currency) based either on the user's preapproval
    currency choice or based on the current locale.
    """
    currency = preapproval.currency if preapproval else None
    tier = Price.objects.get(pk=pay_request['request']['priceTier'])
    price, currency, locale = tier.get_price_data(currency=currency)
    return tier, price, currency


def _payment_done(request, payment, action='PAY_COMPLETE'):
    if action == 'PAY_COMPLETE':
        tasks.payment_notify.delay(payment.pk)
    # TODO(Kumar) when canceled, notify app. bug 741588
    InappPayLog.log(request, action, config=payment.config)
    log.debug('in-app payment %s for payment %s' % (action, payment.pk))


def _serializable_req(pay_req):
    """
    Convert payment request json (from signed JWT)
    to dict that can be serialized.
    """
    pay_req = pay_req.copy()
    del pay_req['_config']
    return pay_req
