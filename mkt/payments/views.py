import commonware.log
import jingo
from session_csrf import anonymous_csrf
from waffle.decorators import waffle_switch

from amo.decorators import login_required, post_required, write, allow_embed
from mkt.payments.decorators import require_inapp_request
from mkt.payments.models import InappPayLog


log = commonware.log.getLogger('z.inapp')


@require_inapp_request
@anonymous_csrf
@allow_embed
@write
@waffle_switch('in-app-payments-ui')
def pay_start(request, signed_req, pay_req):
    InappPayLog.log(request, 'PAY_START', config=pay_req['_config'])
    data = dict(price=pay_req['request']['price'],
                currency=pay_req['request']['currency'],
                item=pay_req['request']['name'],
                description=pay_req['request']['description'],
                signed_request=signed_req)
    return jingo.render(request, 'payments/pay_start.html', data)


@require_inapp_request
@anonymous_csrf
@allow_embed
@login_required
@post_required
@write
@waffle_switch('in-app-payments-ui')
def pay(request, signed_req, pay_req):

    # Do Paypal stuff!

    data = {}
    return jingo.render(request, 'payments/thanks_for_payment.html', data)
