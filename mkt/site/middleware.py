from types import MethodType

from django.conf import settings
from django.http import SimpleCookie, HttpRequest
from django.shortcuts import redirect
from django.utils.cache import patch_vary_headers
from django.utils.translation.trans_real import parse_accept_lang_header

from amo.urlresolvers import Prefixer
from amo.utils import urlparams

import mkt


def _set_cookie(self, key, value='', max_age=None, expires=None, path='/',
                domain=None, secure=False):
    self._resp_cookies[key] = value
    self.COOKIES[key] = value
    if max_age is not None:
        self._resp_cookies[key]['max-age'] = max_age
    if expires is not None:
        self._resp_cookies[key]['expires'] = expires
    if path is not None:
        self._resp_cookies[key]['path'] = path
    if domain is not None:
        self._resp_cookies[key]['domain'] = domain
    if secure:
        self._resp_cookies[key]['secure'] = True


def _delete_cookie(self, key, path='/', domain=None):
    self.set_cookie(key, max_age=0, path=path, domain=domain,
                    expires='Thu, 01-Jan-1970 00:00:00 GMT')
    try:
        del self.COOKIES[key]
    except KeyError:
        pass


class RequestCookiesMiddleware(object):
    """
    Allows setting and deleting of cookies from requests in exactly the same
    way as we do for responses.

        >>> request.set_cookie('name', 'value')

    The `set_cookie` and `delete_cookie` are exactly the same as the ones
    built into Django's `HttpResponse` class.

    I had a half-baked cookie middleware (pun intended), but then I stole this
    from Paul McLanahan: http://paulm.us/post/1660050353/cookies-for-django
    """

    def process_request(self, request):
        request._resp_cookies = SimpleCookie()
        request.set_cookie = MethodType(_set_cookie, request, HttpRequest)
        request.delete_cookie = MethodType(_delete_cookie, request,
                                           HttpRequest)

    def process_response(self, request, response):
        if getattr(request, '_resp_cookies', None):
            response.cookies.update(request._resp_cookies)
        return response


class FixLegacyLocaleMiddleware(object):
    """
    Redirect legacy /<lang>/ URLs to ?lang=<lang> so `LocaleMiddleware`
    can then set a cookie.

    TODO: Maybe we want to allow this for regions too so people can share
          nicely formatted, region-prefixed links.
    """

    def process_request(self, request):
        lang, _, rest = Prefixer(request).split_path(request.path)
        if lang.lower() in settings.LANGUAGE_URL_MAP:
            # Strip /<lang> from URL.
            new_path = request.get_full_path().lstrip('/').partition('/')[2]
            if not new_path.startswith('/'):
                new_path = '/' + new_path
            # I can sleep better with a 302.
            return redirect(urlparams(new_path, lang=lang.lower()))


class LocaleMiddleware(object):
    """Figure out the user's locale and store it in a cookie."""

    def process_request(self, request):
        request.LANG = settings.LANGUAGE_CODE

        remembered = request.COOKIES.get('lang', '').lower()
        if remembered in settings.LANGUAGE_URL_MAP:
            request.LANG = settings.LANGUAGE_URL_MAP[remembered]

        if 'lang' in request.GET or not remembered:
            language = Prefixer(request).get_language()
            if language:
                request.LANG = language

        if not remembered or remembered != request.LANG:
            request.set_cookie('lang', request.LANG)

    def process_response(self, request, response):
        if 'lang' in request.COOKIES:
            patch_vary_headers(response, ['Accept-Language'])
        return response


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def process_request(self, request):
        regions = mkt.regions.REGIONS_DICT
        request.REGION = mkt.regions.WORLDWIDE

        remembered = request.COOKIES.get('region')
        if not remembered:
            # TODO: Do geolocation magic.

            # This gives us something like: [('en-us', 1.0), ('fr', 0.5)]
            header = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
            accept_lang = parse_accept_lang_header(header.lower())

            # If our locale is `en-US`, then exclude the Worldwide region.
            if (request.LANG == settings.LANGUAGE_CODE and accept_lang and
                accept_lang[0][0] == request.LANG.lower()):
                choices = mkt.regions.REGIONS_CHOICES[1:]
            else:
                choices = mkt.regions.REGIONS_CHOICES

            # Try to find a suitable region.
            for name, region in choices:
                if region.default_language == request.LANG:
                    request.REGION = region
                    break
        elif remembered in regions:
            request.REGION = regions[remembered]

        choice = request.GET.get('region')
        if choice in regions:
            request.REGION = regions[choice]

        current = request.REGION.slug
        if not remembered or remembered.lower() != current:
            request.set_cookie('region', current)

    def process_response(self, request, response):
        if 'region' in request.COOKIES:
            patch_vary_headers(response, ['Accept-Language'])
        return response


class VaryOnAJAXMiddleware(object):

    def process_response(self, request, response):
        patch_vary_headers(response, ['X-Requested-With'])
        return response
