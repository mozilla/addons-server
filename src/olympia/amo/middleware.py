import contextlib
import re
import socket
import uuid

from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import transaction
from django.urls import is_valid_path
from django.http import (
    HttpResponsePermanentRedirect, HttpResponseRedirect,
    JsonResponse)
from django.middleware import common
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.encoding import force_text, iri_to_uri
from django.utils.translation import activate, ugettext_lazy as _

from rest_framework import permissions

import MySQLdb as mysql

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

        # Always use a 302 redirect to avoid users being stuck in case of
        # accidental misconfiguration.
        redirect_type = HttpResponseRedirect

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
            query = request.GET.dict()
            query.pop('lang')
            return redirect_type(urlparams(new_path, **query))

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            full_path = quote(full_path.encode('utf-8'))

            if query_string:
                query_string = force_text(query_string, errors='ignore')
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


class AuthenticationMiddlewareWithoutAPI(AuthenticationMiddleware):
    """
    Like AuthenticationMiddleware, but disabled for the API, which uses its
    own authentication mechanism.
    """

    def process_request(self, request):
        if request.is_api and not auth_path.match(request.path):
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


class NonAtomicRequestsForSafeHttpMethodsMiddleware(MiddlewareMixin):
    """
    Middleware to make the view non-atomic if the HTTP method used is safe,
    in order to avoid opening and closing a useless transaction.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        # This uses undocumented django APIS:
        # - transaction.get_connection() followed by in_atomic_block property,
        #   which we need to make sure we're not messing with a transaction
        #   that has already started (which happens in tests using the regular
        #   TestCase class)
        # - _non_atomic_requests(), which set the property to prevent the
        #   transaction on the view itself. We can't use non_atomic_requests
        #   (without the '_') as it returns a *new* view, and we can't do that
        #   in a middleware, we need to modify it in place and return None so
        #   that the rest of the middlewares are run.
        is_method_safe = request.method in ('HEAD', 'GET', 'OPTIONS', 'TRACE')
        if is_method_safe and not transaction.get_connection().in_atomic_block:
            transaction._non_atomic_requests(view_func, using='default')
        return None


class ReadOnlyMiddleware(MiddlewareMixin):
    """Middleware that announces a downtime which for us usually means
    putting the site into read only mode.

    Supports issuing `Retry-After` header.
    """
    ERROR_MSG = _(
        u'Some features are temporarily disabled while we '
        u'perform website maintenance. We\'ll be back to '
        u'full capacity shortly.')

    def process_request(self, request):
        if not settings.READ_ONLY:
            return

        if request.is_api:
            writable_method = request.method not in permissions.SAFE_METHODS
            if writable_method:
                return JsonResponse({'error': self.ERROR_MSG}, status=503)
        elif request.method == 'POST':
            return render(request, 'amo/read-only.html', status=503)

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
