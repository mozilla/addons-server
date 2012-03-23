import functools
import sys

from django import http

import commonware.log
import jingo

from mkt.payments.models import InappPayLog
from mkt.payments.verify import verify_request, InappPaymentError


log = commonware.log.getLogger('z.inapp')


def require_inapp_request(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kw):
        signed_req = request.GET.get('req') or request.POST.get('req')
        if not signed_req:
            return http.HttpResponseBadRequest()
        try:
            req = verify_request(signed_req)
        except InappPaymentError, exc:
            etype, val, tb = sys.exc_info()
            InappPayLog.log(request, 'EXCEPTION', app_public_key=exc.app_id,
                            exc_class=etype.__name__)
            log.info(u'%s: %s' % (etype.__name__, val))
            return jingo.render(request, 'payments/error.html')
        return view(request, signed_req, req, *args, **kw)
    return wrapper
