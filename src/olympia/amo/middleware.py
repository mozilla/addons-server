import contextlib
import os
import re
import uuid
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import (
    Http404,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    JsonResponse,
)
from django.middleware import common
from django.template.response import TemplateResponse
from django.urls import is_valid_path
from django.utils.cache import (
    add_never_cache_headers,
    get_max_age,
    patch_cache_control,
    patch_vary_headers,
)
from django.utils.crypto import constant_time_compare
from django.utils.deprecation import MiddlewareMixin
from django.utils.encoding import force_str, iri_to_uri
from django.utils.translation import activate, gettext_lazy as _

import MySQLdb as mysql
from django_statsd.clients import statsd
from rest_framework import permissions

import olympia.core.logger
from olympia import amo
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.verify import (
    IdentificationError,
    check_and_update_fxa_access_token,
)

from . import urlresolvers
from .reverse import set_url_prefix
from .templatetags.jinja_helpers import urlparams


log = olympia.core.logger.getLogger('amo.middleware')

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

        set_url_prefix(prefixer)
        full_path = prefixer.fix(prefixer.shortened_path)

        if prefixer.app == amo.MOBILE.short and request.path.rstrip('/').endswith(
            '/' + amo.MOBILE.short
        ):
            return redirect_type(request.path.replace('/mobile', '/android'))

        if ('lang' in request.GET or 'app' in request.GET) and not re.match(
            settings.SUPPORTED_NONAPPS_NONLOCALES_REGEX, prefixer.shortened_path
        ):
            # Blank out the locale so that we can set a new one.  Remove
            # lang/app from query params so we don't have an infinite loop.
            prefixer.locale = ''
            new_path = prefixer.fix(prefixer.shortened_path)
            query = request.GET.dict()
            query.pop('app', None)
            query.pop('lang', None)
            return redirect_type(urlparams(new_path, **query))

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            full_path = quote(full_path.encode('utf-8'))

            if query_string:
                query_string = force_str(query_string, errors='ignore')
                full_path = f'{full_path}?{query_string}'

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
            return super().process_request(request)


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

        new_response = super().process_response(request, response)

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
        if (
            response.status_code == 404
            and request.path_info.endswith('/')
            and not is_valid_path(request.path_info)
            and is_valid_path(request.path_info[:-1])
        ):
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
            return super().process_request(request)


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
        'Some features are temporarily disabled while we '
        "perform website maintenance. We'll be back to "
        'full capacity shortly.'
    )

    def render_html_error(self, request):
        response = TemplateResponse(request, 'amo/read-only.html', status=503)
        # render() is normally called behind the scenes by django's base
        # handler inside get_response(), but here we might be bypassing that,
        # so we need to force the rendering ourselves.
        response.render()
        return response

    def render_readonly_api_error(self, request):
        return JsonResponse({'error': self.ERROR_MSG}, status=503)

    def process_request(self, request):
        if not settings.READ_ONLY:
            return

        if request.is_api:
            writable_method = request.method not in permissions.SAFE_METHODS
            if writable_method:
                return self.render_readonly_api_error(request)
        elif request.method == 'POST':
            return self.render_html_error(request)

    def process_exception(self, request, exception):
        if not settings.READ_ONLY:
            return

        if isinstance(exception, mysql.OperationalError):
            if request.is_api:
                return self.render_readonly_api_error(request)
            return self.render_html_error(request)


class SetRemoteAddrFromForwardedFor(MiddlewareMixin):
    """
    Set REMOTE_ADDR from HTTP_X_FORWARDED_FOR if necessary.

    The request flow is either:
    Client -> CDN -> Load balancer -> WSGI proxy -> addons-server.
    or
    Client -> Load balancer -> WSGI proxy -> addons-server.

    Currently:
    - CDN is CloudFront
    - Load Balancer is either a classic ELB (AWS) or GKE Ingress (GCP)
    - WSGI proxy is nginx + uwsgi

    CloudFront is set up to add a X-Request-Via-CDN header set to a secret
    value known to us so we can verify the request did originate from the CDN.

    Nginx converts X-Request-Via-CDN and X-Forwarded-For to
    HTTP_X_REQUEST_VIA_CDN and HTTP_X_FORWARDED_FOR, respectively.

    The X-Forwarded-For header is potentially user input. When intermediary
    servers in the flow described above add their own IP to it, they are always
    appending to the list, so we can only trust specific positions starting
    from the right, anything else cannot be trusted.

    CloudFront always makes origin requests with a X-Forwarded-For header
    set to "Client IP, CDN IP", so the client IP will be second to last for a
    CDN request.

    On AWS, the classic ELB we're using does not make any alterations to
    X-Forwarded-For.

    On GCP, GKE Ingress appends its own IP to that header, resulting
    in a value of "Client IP, CDN IP, GKE Ingress IP", so the client IP will be
    third to last.

    If the request didn't come from the CDN and is a direct origin request, on
    AWS we can use REMOTE_ADDR, but on GCP we'd get the GKE Ingress IP, and the
    X-Forwarded-For value will be "Client IP, GKE Ingress IP", so the client IP
    will be second to last.
    """

    def is_request_from_cdn(self, request):
        return settings.SECRET_CDN_TOKEN and constant_time_compare(
            request.META.get('HTTP_X_REQUEST_VIA_CDN'), settings.SECRET_CDN_TOKEN
        )

    def is_request_from_gcp_environement(self, request):
        return os.environ.get('DEPLOY_PLATFORM') == 'gcp'

    def process_request(self, request):
        position = 1
        x_forwarded_for_header = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for_header:
            if self.is_request_from_cdn(request):
                position += 1
            if self.is_request_from_gcp_environement(request):
                position += 1
            # If position is greater than 1 then we need to fix REMOTE_ADDR by
            # looking into HTTP_X_FORWARDED_FOR, otherwise we should ignore it.
            if position > 1:
                try:
                    value = x_forwarded_for_header.rsplit(sep=',', maxsplit=position)[
                        -position
                    ].strip()
                    if not value:
                        raise IndexError
                    request.META['REMOTE_ADDR'] = value
                except IndexError:
                    # Shouldn't happen, must be a misconfiguration, raise an error
                    # rather than potentially use/record incorrect IPs.
                    raise ImproperlyConfigured('Invalid HTTP_X_FORWARDED_FOR')


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


class CacheControlMiddleware:
    """Middleware to add Cache-Control: max-age=xxx header to responses that
    should be cached, Cache-Control: s-maxage:0 to responses that should not.

    The only responses that should be cached are API, unauthenticated responses
    from "safe" HTTP verbs, or responses that already had a max-age set before
    being processed by this middleware. In that last case, the Cache-Control
    header already present is left intact.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        max_age_from_response = get_max_age(response)
        request_conditions = (
            request.is_api
            and request.method in ('GET', 'HEAD')
            and 'HTTP_AUTHORIZATION' not in request.META
            and 'disable_caching' not in request.GET
        )
        response_conditions = (
            not response.cookies
            and response.status_code >= 200
            and response.status_code < 400
            and not max_age_from_response
        )
        if request_conditions and response_conditions:
            patch_cache_control(response, max_age=settings.API_CACHE_DURATION)
        elif max_age_from_response is None:
            patch_cache_control(response, s_maxage=0)
        return response


class LBHeartbeatMiddleware:
    """Middleware to capture request to /__lbheartbeat__ and return a 200.
    Must be placed above CommonMiddleware to work with ELB.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/__lbheartbeat__':
            response = HttpResponse(status=200)
            add_never_cache_headers(response)
            return response
        return self.get_response(request)


class TokenValidMiddleware:
    """Middleware to check the FxA auth tokens haven't expired, and refresh if
    necessary.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # API requests are validated in SessionIDAuthentication
        if not getattr(request, 'is_api', False):
            if SESSION_KEY not in request.session:
                # Without SESSION_KEY the session is definately anonymous so assume that
                request.user = AnonymousUser()
            else:
                try:
                    check_and_update_fxa_access_token(request)
                except IdentificationError:
                    log.info(f'Failed refreshing access_token for {request.user.id}')
                    return redirect_for_login(request)
        return self.get_response(request)


class GraphiteMiddlewareNoAuth(MiddlewareMixin):
    """Like django-statsd's GraphiteMiddleware, but without the request.auth.*
    pings that would force us to evaluate request.user."""

    def process_response(self, request, response):
        statsd.incr('response.%s' % response.status_code)
        return response

    def process_exception(self, request, exception):
        if not isinstance(exception, Http404):
            statsd.incr('response.500')
