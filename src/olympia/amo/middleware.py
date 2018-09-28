import contextlib
import re
import socket
import urllib
import uuid

from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import is_valid_path
from django.http import (
    HttpResponsePermanentRedirect, HttpResponseRedirect,
    JsonResponse)
from django.middleware import common
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.encoding import force_bytes, iri_to_uri
from django.utils.translation import activate, ugettext_lazy as _

import MySQLdb as mysql
from corsheaders.middleware import CorsMiddleware as _CorsMiddleware

from olympia import amo
from olympia.amo.utils import render

from . import urlresolvers
from .templatetags.jinja_helpers import urlparams


auth_path = re.compile('%saccounts/authenticate/?$' % settings.DRF_API_REGEX)


class LocaleAndAppURLMiddleware(MiddlewareMixin):
    """
    1. search for locale first
    2. see if there are acceptable apps
    3. save those matched parameters in the request
    4. strip them from the URL so we can do stuff
    """

    def process_request(self, request):
        # Find locale, app
        prefixer = urlresolvers.Prefixer(request)
        if settings.DEBUG:
            redirect_type = HttpResponseRedirect
        else:
            redirect_type = HttpResponsePermanentRedirect
        urlresolvers.set_url_prefix(prefixer)
        full_path = prefixer.fix(prefixer.shortened_path)

        if (prefixer.app == amo.MOBILE.short and
                request.path.rstrip('/').endswith('/' + amo.MOBILE.short)):
            return redirect_type(request.path.replace('/mobile', '/android'))

        if ('lang' in request.GET and not re.match(
                settings.SUPPORTED_NONAPPS_NONLOCALES_REGEX,
                prefixer.shortened_path)):
            # Blank out the locale so that we can set a new one.  Remove lang
            # from query params so we don't have an infinite loop.
            prefixer.locale = ''
            new_path = prefixer.fix(prefixer.shortened_path)
            query = dict((force_bytes(k), request.GET[k]) for k in request.GET)
            query.pop('lang')
            return redirect_type(urlparams(new_path, **query))

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            full_path = urllib.quote(full_path.encode('utf-8'))

            if query_string:
                query_string = query_string.decode('utf-8', 'ignore')
                full_path = u'%s?%s' % (full_path, query_string)

            response = redirect_type(full_path)
            # Cache the redirect for a year.
            if not settings.DEBUG:
                patch_cache_control(response, max_age=60 * 60 * 24 * 365)

            # Vary on Accept-Language or User-Agent if we changed the locale or
            # app.
            old_app = prefixer.app
            old_locale = prefixer.locale
            new_locale, new_app, _ = prefixer.split_path(full_path)

            if old_locale != new_locale:
                patch_vary_headers(response, ['Accept-Language'])
            if old_app != new_app:
                patch_vary_headers(response, ['User-Agent'])
            return response

        request.path_info = '/' + prefixer.shortened_path
        request.LANG = prefixer.locale or prefixer.get_language()
        activate(request.LANG)
        request.APP = amo.APPS.get(prefixer.app, amo.FIREFOX)

        # Match legacy api requests too - IdentifyAPIRequestMiddleware is v3+
        # TODO - remove this when legacy_api goes away
        # https://github.com/mozilla/addons-server/issues/9274
        request.is_legacy_api = request.path_info.startswith('/api/')


class AuthenticationMiddlewareWithoutAPI(AuthenticationMiddleware):
    """
    Like AuthenticationMiddleware, but disabled for the API, which uses its
    own authentication mechanism.
    """
    def process_request(self, request):
        legacy_or_drf_api = request.is_api or request.is_legacy_api
        if legacy_or_drf_api and not auth_path.match(request.path):
            request.user = AnonymousUser()
        else:
            return super(
                AuthenticationMiddlewareWithoutAPI,
                self).process_request(request)


class NoVarySessionMiddleware(SessionMiddleware):
    """
    SessionMiddleware sets Vary: Cookie anytime request.session is accessed.
    request.session is accessed indirectly anytime request.user is touched.
    We always touch request.user to see if the user is authenticated, so every
    request would be sending vary, so we'd get no caching.

    We skip the cache in Zeus if someone has an AMOv3+ cookie, so varying on
    Cookie at this level only hurts us.
    """
    def process_response(self, request, response):
        if settings.READ_ONLY:
            return response

        # Let SessionMiddleware do its processing but prevent it from changing
        # the Vary header.
        vary = None
        if hasattr(response, 'get'):
            vary = response.get('Vary', None)

        new_response = (
            super(NoVarySessionMiddleware, self)
            .process_response(request, response))

        if vary:
            new_response['Vary'] = vary
        else:
            del new_response['Vary']
        return new_response


class RemoveSlashMiddleware(MiddlewareMixin):
    """
    Middleware that tries to remove a trailing slash if there was a 404.

    If the response is a 404 because url resolution failed, we'll look for a
    better url without a trailing slash.
    """

    def process_response(self, request, response):
        if (response.status_code == 404 and
                request.path_info.endswith('/') and
                not is_valid_path(request.path_info) and
                is_valid_path(request.path_info[:-1])):
            # Use request.path because we munged app/locale in path_info.
            newurl = request.path[:-1]
            if request.GET:
                with safe_query_string(request):
                    newurl += '?' + request.META.get('QUERY_STRING', '')
            return HttpResponsePermanentRedirect(newurl)
        else:
            return response


@contextlib.contextmanager
def safe_query_string(request):
    """
    Turn the QUERY_STRING into a unicode- and ascii-safe string.

    We need unicode so it can be combined with a reversed URL, but it has to be
    ascii to go in a Location header.  iri_to_uri seems like a good compromise.
    """
    qs = request.META.get('QUERY_STRING', '')
    try:
        request.META['QUERY_STRING'] = iri_to_uri(qs)
        yield
    finally:
        request.META['QUERY_STRING'] = qs


class CommonMiddleware(common.CommonMiddleware):

    def process_request(self, request):
        with safe_query_string(request):
            return super(CommonMiddleware, self).process_request(request)


class ReadOnlyMiddleware(MiddlewareMixin):
    """Middleware that announces a downtime which for us usually means
    putting the site into read only mode.

    Supports issuing `Retry-After` header.
    """
    ERROR_MSG = _(
        u'Some features are temporarily disabled while we '
        u'perform website maintenance. We\'ll be back to '
        u'full capacity shortly.')

    READ_ONLY_HEADER = 'X-AMO-Read-Only'

    def _render_api_error(self):
        response = JsonResponse({'error': self.ERROR_MSG}, status=503)
        response[self.READ_ONLY_HEADER] = 'true'
        if settings.READ_ONLY_RETRY_AFTER is not None:
            response['Retry-After'] = settings.READ_ONLY_RETRY_AFTER.seconds
        return response

    def process_request(self, request):
        if not settings.READ_ONLY:
            return

        if request.is_api:
            writable_method = request.method in ('POST', 'PUT', 'DELETE')
            if writable_method:
                return self._render_api_error()
        elif request.method == 'POST':
            return render(request, 'amo/read-only.html', status=503)

    def process_response(self, request, response):
        # We haven't set the header yet so it's not an error response
        # set by this middleware so we should default to setting it to
        # `false`
        header_name = self.READ_ONLY_HEADER

        if header_name not in response:
            response[self.READ_ONLY_HEADER] = 'false'
        return response

    def process_exception(self, request, exception):
        if not settings.READ_ONLY:
            return

        if isinstance(exception, mysql.OperationalError):
            if request.is_api:
                return self._render_api_error()
            return render(request, 'amo/read-only.html', status=503)


class SetRemoteAddrFromForwardedFor(MiddlewareMixin):
    """
    Set request.META['REMOTE_ADDR'] from request.META['HTTP_X_FORWARDED_FOR'].

    Our application servers should always be behind a load balancer that sets
    this header correctly.
    """
    def is_valid_ip(self, ip):
        for af in (socket.AF_INET, socket.AF_INET6):
            try:
                socket.inet_pton(af, ip)
                return True
            except socket.error:
                pass
        return False

    def process_request(self, request):
        ips = []

        if 'HTTP_X_FORWARDED_FOR' in request.META:
            xff = [i.strip() for i in
                   request.META['HTTP_X_FORWARDED_FOR'].split(',')]
            ips = [ip for ip in xff if self.is_valid_ip(ip)]
        else:
            return

        ips.append(request.META['REMOTE_ADDR'])

        known = getattr(settings, 'KNOWN_PROXIES', [])
        ips.reverse()

        for ip in ips:
            request.META['REMOTE_ADDR'] = ip
            if ip not in known:
                break


class ScrubRequestOnException(MiddlewareMixin):
    """
    Hide sensitive information so they're not recorded in error logging.
    * passwords in request.POST
    * sessionid in request.COOKIES
    """

    def process_exception(self, request, exception):
        # Get a copy so it's mutable.
        request.POST = request.POST.copy()
        for key in request.POST:
            if 'password' in key.lower():
                request.POST[key] = '******'

        # Remove session id from cookies
        if settings.SESSION_COOKIE_NAME in request.COOKIES:
            request.COOKIES[settings.SESSION_COOKIE_NAME] = '******'
            # Clearing out all cookies in request.META. They will already
            # be sent with request.COOKIES.
            request.META['HTTP_COOKIE'] = '******'


class RequestIdMiddleware(MiddlewareMixin):
    """Middleware that adds a unique request-id to every incoming request.

    This can be used to track a request across different system layers,
    e.g to correlate logs with sentry exceptions.

    We are exposing this request id in the `X-AMO-Request-ID` response header.
    """

    def process_request(self, request):
        request.request_id = uuid.uuid4().hex

    def process_response(self, request, response):
        request_id = getattr(request, 'request_id', None)

        if request_id:
            response['X-AMO-Request-ID'] = request.request_id

        return response


class CorsMiddleware(_CorsMiddleware, MiddlewareMixin):
    """Wrapper to allow old style Middleware to work with django 1.10+.
    Will be unneeded once
    https://github.com/mstriemer/django-cors-headers/pull/3 is merged and a
    new release of django-cors-headers-multi is available."""
    pass
