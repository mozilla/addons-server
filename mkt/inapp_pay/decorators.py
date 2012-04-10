import functools
import sys

from django import http

import commonware.log

from .helpers import render_error
from .models import InappPayLog
from .verify import verify_request, InappPaymentError

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
            exc_class = etype.__name__
            InappPayLog.log(request, 'EXCEPTION', app_public_key=exc.app_id,
                            exc_class=exc_class)
            log.exception('in @require_inapp_request')
            return render_error(request, exc, exc_class=exc_class)
        return view(request, signed_req, req, *args, **kw)
    return wrapper
