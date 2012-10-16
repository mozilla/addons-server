import copy
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
from lib.geoip import GeoIP
from mkt.carriers import get_carrier


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


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def process_request(self, request):
        regions = mkt.regions.REGIONS_DICT

        reg = mkt.regions.WORLDWIDE.slug
        stored_reg = ''

        # If I have a cookie use that region.
        remembered = request.COOKIES.get('region')
        if remembered in regions:
            reg = stored_reg = remembered

        # Re-detect my region only if my *Accept-Language* is different from
        # that of my previous language.

        lang_changed = (get_accept_language(request)
                        not in request.COOKIES.get('lang', '').split(','))
        if not remembered or lang_changed:
            # If our locale is `en-US`, then exclude the Worldwide region.
            if request.LANG == settings.LANGUAGE_CODE:
                choices = mkt.regions.REGIONS_CHOICES[1:]
            else:
                choices = mkt.regions.REGIONS_CHOICES

            # if we faked the user's LANG, and we still don't have a
            # valid region, try from the IP
            if (request.LANG.lower() not in
                request.META.get('HTTP_ACCEPT_LANGUAGE', '').lower()):
                ip_reg = self.geoip.lookup(request.META.get('REMOTE_ADDR'))
                for name, region in choices:
                    if ip_reg == name:
                        reg = region.slug
                        break
            elif request.LANG:
                for name, region in choices:
                    if name.lower() in request.LANG.lower():
                        reg = region.slug
                        break
            # All else failed, try to match against our forced Language.
            if reg == mkt.regions.WORLDWIDE.slug:
                # Try to find a suitable region.
                for name, region in choices:
                    if region.default_language == request.LANG:
                        reg = region.slug
                        break

        choice = request.REQUEST.get('region')
        if choice in regions:
            reg = choice

        a_l = request.META.get('HTTP_ACCEPT_LANGUAGE')

        if reg == 'us' and a_l is not None and not a_l.startswith('en'):
            # Let us default to worldwide if it's not English.
            reg = mkt.regions.WORLDWIDE.slug

        # Update cookie if value have changed.
        if reg != stored_reg:
            request.set_cookie('region', reg)

        request.REGION = regions[reg]

    def process_response(self, request, response):
        patch_vary_headers(response, ['Accept-Language', 'Cookie'])
        return response


class VaryOnAJAXMiddleware(object):

    def process_response(self, request, response):
        patch_vary_headers(response, ['X-Requested-With'])
        return response


class MobileDetectionMiddleware(object):
    """
    If the user has flagged that they are mobile or we were able to detect that
    the user is a mobile user, store that the user is a mobile user. If we find
    that we've previously stored that the user is on mobile, tell the request
    that the user is a mobile user.
    """

    def process_request(self, request):
        mobile_qs = request.GET.get('mobile', False)
        if mobile_qs:
            if mobile_qs == 'false':
                request.delete_cookie('mobile')
            else:
                request.set_cookie('mobile', 'true')

        request.MOBILE = (getattr(request, 'MOBILE', False) or
                          bool(request.COOKIES.get('mobile', False)))


class GaiaDetectionMiddleware(object):
    """
    Same as above for B2G (gaia) devices. /js/mkt/init.js will set the gaia
    cookie to 'true' unless a 'gaia' query parameter overrides it for testing.
    """

    def process_request(self, request):
        gaia_qs = request.GET.get('gaia', False)
        if gaia_qs:
            if gaia_qs == 'false':
                request.delete_cookie('gaia')
            elif gaia_qs == 'true':
                request.set_cookie('gaia', 'true')

        request.GAIA = (getattr(request, 'GAIA', False) or
                        bool(request.COOKIES.get('gaia', False)))


class HijackRedirectMiddleware(object):
    """
    This lets us hijack redirects so we directly return fragment responses
    instead of redirecting and doing lame synchronous page requests.
    """

    def process_response(self, request, response):
        if (getattr(request, 'FRAGMENTS', False) and
                request.method == 'POST' and
                response.status_code in (301, 302)):
            view_url = location = response['Location']
            if get_carrier():
                # Strip carrier from URL.
                view_url = '/'.join(location.split('/')[2:])
            r = copy.copy(request)
            r.method = 'GET'
            # We want only the fragment response.
            r.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
            # Pass back the URI so we can pushState it.
            r.FRAGMENT_URI = location
            view = resolve(view_url)
            response = view.func(r, *view.args, **view.kwargs)
        return response
