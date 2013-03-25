from django.conf import settings
from django.utils.cache import patch_vary_headers

from amo.urlresolvers import set_url_prefix
from mkt.constants.carriers import CARRIER_MAP

from . import set_carrier


class CarrierURLMiddleware(object):
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
        carrier = stored_carrier = None
        is_legacy = False
        set_url_prefix(None)
        set_carrier(None)

        # If I have a cookie use that carrier.
        remembered = request.COOKIES.get('carrier')
        if remembered in CARRIER_MAP:
            carrier = stored_carrier = remembered

        choice = request.REQUEST.get('carrier')
        if choice in CARRIER_MAP:
            carrier = choice
        elif 'carrier' in request.GET:
            # We are clearing the carrier.
            carrier = None

        # Legacy /<carrier>/ (don't break Gaia).
        for name in CARRIER_MAP:
            if request.path.startswith('/%s' % name):
                is_legacy = True
                carrier = name
                break

        # Update cookie if value have changed.
        if carrier != stored_carrier:
            request.set_cookie('carrier', carrier)

        if carrier and is_legacy:
            orig_path = request.path_info
            new_path = orig_path[len(carrier) + 1:] or '/'
            request.path_info = new_path

        set_carrier(carrier)

    def process_response(self, request, response):
        patch_vary_headers(response, ['Accept-Language', 'Cookie'])
        return response
