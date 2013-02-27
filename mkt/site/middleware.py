from types import MethodType

from django import http
from django.conf import settings
from django.core.urlresolvers import resolve
from django.http import SimpleCookie, HttpRequest
from django.utils.cache import patch_vary_headers

import tower

import amo
from amo.urlresolvers import lang_from_accept_header, Prefixer
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


class RedirectPrefixedURIMiddleware(object):
    """
    Strip /<app>/ prefix from URLs.

    Redirect /<lang>/ URLs to ?lang=<lang> so `LocaleMiddleware`
    can then set a cookie.

    Redirect /<region>/ URLs to ?region=<lang> so `RegionMiddleware`
    can then set a cookie.
    """

    def process_request(self, request):
        request.APP = amo.FIREFOX

        path_ = request.get_full_path()
        new_path = None
        new_qs = {}

        lang, app, rest = Prefixer(request).split_path(path_)

        if app:
            # Strip /<app> from URL.
            new_path = rest

        if lang:
            # Strip /<lang> from URL.
            if not new_path:
                new_path = rest
            new_qs['lang'] = lang.lower()

        region, _, rest = path_.lstrip('/').partition('/')
        region = region.lower()

        if region in mkt.regions.REGIONS_DICT:
            # Strip /<region> from URL.
            if not new_path:
                new_path = rest
            new_qs['region'] = region

        if new_path is not None:
            if not new_path or new_path[0] != '/':
                new_path = '/' + new_path
            # TODO: Make this a 301 when we enable region stores in prod.
            return http.HttpResponseRedirect(urlparams(new_path, **new_qs))


def get_accept_language(request):
    a_l = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    return lang_from_accept_header(a_l)


class LocaleMiddleware(object):
    """Figure out the user's locale and store it in a cookie."""

    def process_request(self, request):
        a_l = get_accept_language(request)
        lang, ov_lang = a_l, ''
        stored_lang, stored_ov_lang = '', ''

        remembered = request.COOKIES.get('lang')
        if remembered:
            chunks = remembered.split(',')[:2]

            stored_lang = chunks[0]
            try:
                stored_ov_lang = chunks[1]
            except IndexError:
                pass

            if stored_lang.lower() in settings.LANGUAGE_URL_MAP:
                lang = stored_lang
            if stored_ov_lang.lower() in settings.LANGUAGE_URL_MAP:
                ov_lang = stored_ov_lang

        if 'lang' in request.REQUEST:
            # `get_language` uses request.GET['lang'] and does safety checks.
            ov_lang = a_l
            lang = Prefixer(request).get_language()
        elif a_l != ov_lang:
            # Change if Accept-Language differs from Overridden Language.
            lang = a_l
            ov_lang = ''

        # Update cookie if values have changed.
        if lang != stored_lang or ov_lang != stored_ov_lang:
            request.LANG_COOKIE = ','.join([lang, ov_lang])

        request.LANG = lang
        tower.activate(lang)

    def process_response(self, request, response):
        # We want to change the cookie, but didn't have the response in
        # process request.
        if hasattr(request, 'LANG_COOKIE'):
            response.set_cookie('lang', request.LANG_COOKIE)
        patch_vary_headers(response, ['Accept-Language', 'Cookie'])
        return response


class DeviceDetectionMiddleware(object):
    """If the user has flagged that they are on a device. Store the device."""
    devices = ['mobile', 'gaia', 'tablet']

    def process_request(self, request):
        for device in self.devices:
            # The XMobility middleware might have already set this.
            if getattr(request, device.upper(), False):
                continue

            qs = request.GET.get(device, False)
            cookie = request.COOKIES.get(device, False)
            # If the qs is True or there's a cookie set the device. But not if
            # the qs is False.
            if qs == 'true' or (cookie and not qs == 'false'):
                setattr(request, device.upper(), True)
                continue

            # Otherwise set to False.
            setattr(request, device.upper(), False)

    def process_response(self, request, response):
        for device in self.devices:
            active = getattr(request, device.upper(), False)
            cookie = request.COOKIES.get(device, False)

            if not active and cookie:
                # If the device isn't active, but there is a cookie, remove it.
                response.delete_cookie(device)
            elif active and not cookie:
                # Set the device if it's active and there's no cookie.
                response.set_cookie(device, 'true')

        return response
