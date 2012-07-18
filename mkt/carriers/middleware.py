from django.conf import settings
from django.http import HttpResponsePermanentRedirect

from amo.urlresolvers import set_url_prefix

from . import set_carrier
from .carriers import CarrierPrefixer


class CarrierURLMiddleware:
    """
    Supports psuedo-URL prefixes that define a custom carrier store.

    For example, if you browse the Marketplace at /telefonica/ then this
    middleware will
    1. strip off the telefonica part so all other URLs work as expected;
    2. allow you to access 'telefonica' from mkt.carriers.get_carrier(); and
    3. set a prefix so that reverse('whatever') returns /telefonica/whatever.

    See bug 769421
    """

    def process_request(self, request):
        carrier = None
        set_url_prefix(None)
        set_carrier(None)
        for name in settings.CARRIER_URLS:
            if request.path.startswith('/%s' % name):
                carrier = name
                break
        if carrier:
            orig_path = request.path_info
            request.path_info = orig_path[len('/%s' % carrier):]
            if request.path_info == '' and settings.APPEND_SLASH:
                # e.g. /telefonica -> /telefonica/
                # Note that this is an exceptional case. All other slash
                # appending is handled further down the middleware chain.
                return HttpResponsePermanentRedirect(orig_path + '/')
            set_url_prefix(CarrierPrefixer(request, carrier))
        set_carrier(carrier)
