import re

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.utils.cache import patch_vary_headers


# Mobile user agents.
USER_AGENTS = 'android|fennec|iemobile|iphone|opera (?:mini|mobi)'
USER_AGENTS = re.compile(getattr(settings, 'MOBILE_USER_AGENTS', USER_AGENTS))

# We set a cookie if you explicitly select mobile/no mobile.
COOKIE = getattr(settings, 'MOBILE_COOKIE', 'mobile')


# We do this in zeus for performance, so this exists for the devserver and
# to work out the logic.
class DetectMobileMiddleware(object):

    def process_request(self, request):
        ua = request.META.get('HTTP_USER_AGENT', '').lower()
        mc = request.COOKIES.get(COOKIE)
        if (USER_AGENTS.search(ua) and mc != 'off') or mc == 'on':
            request.META['HTTP_X_MOBILE'] = '1'

    def process_response(self, request, response):
        patch_vary_headers(response, ['User-Agent'])
        return response


class XMobileMiddleware(object):

    def redirect(self, request, base):
        path = base.rstrip('/') + request.path
        if request.GET:
            path += '?' + request.GET.urlencode()
        response = HttpResponsePermanentRedirect(path)
        response['Vary'] = 'X-Mobile'
        return response

    def process_request(self, request):
        try:
            want_mobile = int(request.META.get('HTTP_X_MOBILE', 0))
        except Exception:
            want_mobile = False
        request.MOBILE = want_mobile

    def process_response(self, request, response):
        patch_vary_headers(response, ['X-Mobile'])
        return response
