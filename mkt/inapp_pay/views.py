import hashlib
import uuid

from commonware.response.decorators import xframe_allow
import commonware.log
import jingo
import jinja2
from session_csrf import anonymous_csrf
from tower import ugettext as _
import waffle
from waffle.decorators import waffle_switch

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, get_object_or_404

import amo
from amo.decorators import login_required, post_required, write
from mkt.inapp_pay.decorators import require_inapp_request
from mkt.inapp_pay.models import InappPayLog, InappConfig
import paypal
from stats.models import Contribution


log = commonware.log.getLogger('z.inapp_pay')


@require_inapp_request
@anonymous_csrf
@xframe_allow
@write
@waffle_switch('in-app-payments-ui')
def pay_start(request, signed_req, pay_req):
    InappPayLog.log(request, 'PAY_START', config=pay_req['_config'])
    data = dict(price=pay_req['request']['price'],
                currency=pay_req['request']['currency'],
                item=pay_req['request']['name'],
                description=pay_req['request']['description'],
                signed_request=signed_req)
    return jingo.render(request, 'inapp_pay/pay_start.html', data)


@require_inapp_request
@anonymous_csrf
@xframe_allow
@transaction.commit_on_success
@login_required
@post_required
@write
@waffle_switch('in-app-payments-ui')
def pay(request, signed_req, pay_req):
    amount = pay_req['request']['price']
    currency = pay_req['request']['currency']
    source = request.POST.get('source', '')
    addon = pay_req['_config'].addon
    # L10n: {0} is the product name. {1} is the application name
    contrib_for = _(u'In-app payment for {0} to {1}').format(
                                jinja2.escape(pay_req['request']['name']),
                                jinja2.escape(addon.name))
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
            email=addon.paypal_id,
            ip=request.META.get('REMOTE_ADDR'),
            memo=contrib_for,
            pattern='inapp_pay.pay_done',
            preapproval=preapproval,
            qs={'realurl': request.POST.get('realurl')},
            slug=pay_req['_config'].pk,  # passed to pay_done() via reverse()
            uuid=uuid_
        ))
    except paypal.PaypalError:
        paypal.paypal_log_cef(request, addon, uuid_,
                              'in-app PayKey Failure', 'PAYKEYFAIL',
                              'There was an error getting the paykey')
        log.error(u'Error getting paykey, in-app payment: %s'
                  % pay_req['_config'].pk,
                  exc_info=True)
        InappPayLog.log(request, 'PAY_ERROR', config=pay_req['_config'])
        return jingo.render(request, 'inapp_pay/error.html', {})

    if paykey:
        contrib = Contribution(addon_id=addon.id, amount=amount,
                               source=source, source_locale=request.LANG,
                               currency=currency, uuid=str(uuid_),
                               type=amo.CONTRIB_INAPP_PENDING,
                               paykey=paykey, user=request.amo_user)
        log.debug('Storing in-app payment contrib for uuid: %s' % uuid_)

        # If this was a pre-approval, it's completed already, we'll
        # double check this with PayPal, just to be sure nothing went wrong.
        if status == 'COMPLETED':
            paypal.paypal_log_cef(request, addon, uuid_,
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

    else:
        log.error('No paykey present for uuid: %s' % uuid_)

    InappPayLog.log(request, 'PAY', config=pay_req['_config'])
    log.debug('Got paykey for in-app payment config %s by user: %s'
              % (pay_req['_config'].pk, request.amo_user.pk))

    url = '%s?paykey=%s' % (settings.PAYPAL_FLOW_URL, paykey)
    if status != 'COMPLETED':
        # Start pay flow.
        return redirect(url)

    # Payment was completed using pre-auth. Woo!
    _log_payment_done(request, pay_req['_config'], uuid_)
    return jingo.render(request, 'inapp_pay/thanks_for_payment.html', {})


@anonymous_csrf
@xframe_allow
@transaction.commit_on_success
@login_required
@write
@waffle_switch('in-app-payments-ui')
def pay_done(request, config_pk, status):
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
    if status == 'complete':
        cnt.update(type=amo.CONTRIB_INAPP)
        tpl = 'inapp_pay/thanks_for_payment.html'
        action = 'PAY_COMPLETE'
    elif status == 'cancel':
        tpl = 'inapp_pay/payment_cancel.html'
        action = 'PAY_CANCEL'
    else:
        raise ValueError('Unexpected status: %r' % status)
    _log_payment_done(request, cfg, uuid_, action=action)
    return jingo.render(request, tpl, {})


def _log_payment_done(request, config, uuid_, action='PAY_COMPLETE'):
    InappPayLog.log(request, action, config=config)
    log.debug('In-app payment done for %s, uuid %r' % (config.pk, uuid_))
