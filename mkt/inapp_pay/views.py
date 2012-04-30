import hashlib
import uuid

from commonware.response.decorators import xframe_allow
import commonware.log
import jingo
from session_csrf import anonymous_csrf
from tower import ugettext as _
import waffle
from waffle.decorators import waffle_switch

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, get_object_or_404

import amo
from amo.decorators import (login_required, no_login_required,
                            post_required, write)
import paypal
from stats.models import Contribution

from .decorators import require_inapp_request
from .helpers import render_error
from .models import InappPayment, InappPayLog, InappConfig
from . import tasks


log = commonware.log.getLogger('z.inapp_pay')


@xframe_allow
@require_inapp_request
@anonymous_csrf
@write
@waffle_switch('in-app-payments-ui')
def pay_start(request, signed_req, pay_req):
    InappPayLog.log(request, 'PAY_START', config=pay_req['_config'])
    data = dict(price=pay_req['request']['price'],
                product=pay_req['_config'].addon,
                currency=pay_req['request']['currency'],
                item=pay_req['request']['name'],
                description=pay_req['request']['description'],
                signed_request=signed_req)
    tasks.fetch_product_image.delay(pay_req['_config'].pk,
                                    _serializable_req(pay_req))
    if not request.user.is_authenticated():
        return jingo.render(request, 'inapp_pay/login.html', data)
    preapproval = None
    if request.amo_user:
        preapproval = request.amo_user.get_preapproval()
    if not preapproval:
        return jingo.render(request, 'inapp_pay/nowallet.html', data)
    return jingo.render(request, 'inapp_pay/pay_start.html', data)


@xframe_allow
@require_inapp_request
@login_required
@post_required
@write
@waffle_switch('in-app-payments-ui')
def pay(request, signed_req, pay_req):
    amount = pay_req['request']['price']
    currency = pay_req['request']['currency']
    source = request.POST.get('source', '')
    product = pay_req['_config'].addon
    # L10n: {0} is the product name. {1} is the application name
    contrib_for = (_(u'Mozilla Marketplace in-app payment for {0} to {1}')
                   .format(pay_req['request']['name'], product.name))
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()

    paykey, status = '', ''
    preapproval = None
    if waffle.flag_is_active(request, 'allow-pre-auth') and request.amo_user:
        preapproval = request.amo_user.get_preapproval()

    try:
        paykey, status = paypal.get_paykey(dict(
            amount=amount,
            chains=settings.PAYPAL_CHAINS,
            currency=currency,
            email=product.paypal_id,
            ip=request.META.get('REMOTE_ADDR'),
            memo=contrib_for,
            pattern='inapp_pay.pay_status',
            preapproval=preapproval,
            qs={'realurl': request.POST.get('realurl')},
            slug=pay_req['_config'].pk,  # passed to pay_done() via reverse()
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
        contrib = Contribution(addon_id=product.id, amount=amount,
                               source=source, source_locale=request.LANG,
                               currency=currency, uuid=str(uuid_),
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
            if paypal.check_purchase(paykey) == 'COMPLETED':
                log.debug('Check in-app payment is completed for uuid: %s'
                          % uuid_)
                contrib.type = amo.CONTRIB_INAPP
            else:
                # In this case PayPal disagreed, we should not be trusting
                # what get_paykey said. Which is a worry.
                log.error('Check in-app payment failed on uuid: %s' % uuid_)
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
        return redirect(url)

    # Payment was completed using pre-auth. Woo!
    _payment_done(request, payment)

    c = dict(price=pay_req['request']['price'],
             product=pay_req['_config'].addon,
             currency=pay_req['request']['currency'],
             item=pay_req['request']['name'],
             description=pay_req['request']['description'],
             signed_request=signed_req)
    return jingo.render(request, 'inapp_pay/complete.html', c)


@xframe_allow
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
                Contribution.DoesNotExist):
            log.error('PayPal returned invalid uuid %r from in-app payment'
                      % uuid_, exc_info=True)
            return jingo.render(request, 'inapp_pay/error.html')
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


def _payment_done(request, payment, action='PAY_COMPLETE'):
    if action == 'PAY_COMPLETE':
        tasks.payment_notify.delay(payment.pk)
    # TODO(Kumar) when canceled, notify app. bug 741588
    InappPayLog.log(request, action, config=payment.config)
    log.debug('in-app payment %s for payment %s' % (action, payment.pk))


# @cache_page(60 * 60 * 24 * 365)
@no_login_required
def mozmarket_lib(request):
    return jingo.render(request, 'inapp_pay/library.js',
                        content_type='text/javascript')


def _serializable_req(pay_req):
    """
    Convert payment request json (from signed JWT)
    to dict that can be serialized.
    """
    pay_req = pay_req.copy()
    del pay_req['_config']
    return pay_req
