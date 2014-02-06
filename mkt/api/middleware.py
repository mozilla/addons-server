import hashlib
import hmac
import re
import time
from urllib import urlencode

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.middleware.transaction import TransactionMiddleware
from django.utils.cache import patch_vary_headers

import commonware.log
from django_statsd.clients import statsd
from django_statsd.middleware import (GraphiteRequestTimingMiddleware,
                                      TastyPieRequestTimingMiddleware)
from multidb.pinning import (pin_this_thread, this_thread_is_pinned,
                             unpin_this_thread)
from multidb.middleware import PinningRouterMiddleware

from mkt.api.models import Access, ACCESS_TOKEN, Token
from mkt.api.oauth import OAuthServer
from mkt.carriers import get_carrier
from users.models import UserProfile


log = commonware.log.getLogger('z.api')


class RestOAuthMiddleware(object):
    """
    This is based on https://github.com/amrox/django-tastypie-two-legged-oauth
    with permission.
    """

    def process_request(self, request):
        # For now we only want these to apply to the API.
        # This attribute is set in RedirectPrefixedURIMiddleware.
        if not getattr(request, 'API', False):
            return

        if not settings.SITE_URL:
            raise ValueError('SITE_URL is not specified')

        # Set up authed_from attribute.
        if not hasattr(request, 'authed_from'):
            request.authed_from = []

        auth_header_value = request.META.get('HTTP_AUTHORIZATION')
        if (not auth_header_value and
            'oauth_token' not in request.META['QUERY_STRING']):
            self.user = AnonymousUser()
            log.info('No HTTP_AUTHORIZATION header')
            return

        # Set up authed_from attribute.
        auth_header = {'Authorization': auth_header_value}
        method = getattr(request, 'signed_method', request.method)
        oauth = OAuthServer()
        if ('oauth_token' in request.META['QUERY_STRING'] or
            'oauth_token' in auth_header_value):
            # This is 3-legged OAuth.
            log.info('Trying 3 legged OAuth')
            try:
                valid, oauth_request = oauth.verify_request(
                    request.build_absolute_uri(),
                    method, headers=auth_header,
                    require_resource_owner=True)
            except ValueError:
                log.error('ValueError on verifying_request', exc_info=True)
                return
            if not valid:
                log.error(u'Cannot find APIAccess token with that key: %s'
                          % oauth.attempted_key)
                return
            uid = Token.objects.filter(
                token_type=ACCESS_TOKEN,
                key=oauth_request.resource_owner_key).values_list(
                    'user_id', flat=True)[0]
            request.amo_user = UserProfile.objects.select_related(
                'user').get(pk=uid)
            request.user = request.amo_user.user
        else:
            # This is 2-legged OAuth.
            log.info('Trying 2 legged OAuth')
            try:
                valid, oauth_request = oauth.verify_request(
                    request.build_absolute_uri(),
                    method, headers=auth_header,
                    require_resource_owner=False)
            except ValueError:
                log.error('ValueError on verifying_request', exc_info=True)
                return
            if not valid:
                log.error(u'Cannot find APIAccess token with that key: %s'
                          % oauth.attempted_key)
                return
            uid = Access.objects.filter(
                key=oauth_request.client_key).values_list(
                    'user_id', flat=True)[0]
            request.amo_user = UserProfile.objects.select_related(
                'user').get(pk=uid)
            request.user = request.amo_user.user

        # But you cannot have one of these roles.
        denied_groups = set(['Admins'])
        roles = set(request.amo_user.groups.values_list('name', flat=True))
        if roles and roles.intersection(denied_groups):
            log.info(u'Attempt to use API with denied role, user: %s'
                     % request.amo_user.pk)
            # Set request attributes back to None.
            request.user = request.amo_user = None
            return

        if request.user:
            request.authed_from.append('RestOAuth')

        log.info('Successful OAuth with user: %s' % request.user)


class RestSharedSecretMiddleware(object):

    def process_request(self, request):
        # For now we only want these to apply to the API.
        # This attribute is set in RedirectPrefixedURIMiddleware.
        if not getattr(request, 'API', False):
            return

        # Set up authed_from attribute.
        if not hasattr(request, 'authed_from'):
            request.authed_from = []

        header = request.META.get('HTTP_AUTHORIZATION', '').split(None, 1)
        if header and header[0].lower() == 'mkt-shared-secret':
            auth = header[1]
        else:
            auth = request.GET.get('_user')
        if not auth:
            log.info('API request made without shared-secret auth token')
            return
        try:
            email, hm, unique_id = str(auth).split(',')
            consumer_id = hashlib.sha1(
                email + settings.SECRET_KEY).hexdigest()
            matches = hmac.new(unique_id + settings.SECRET_KEY,
                               consumer_id, hashlib.sha512).hexdigest() == hm
            if matches:
                try:
                    request.amo_user = UserProfile.objects.select_related(
                        'user').get(email=email)
                    request.user = request.amo_user.user
                    request.authed_from.append('RestSharedSecret')
                except UserProfile.DoesNotExist:
                    log.info('Auth token matches absent user (%s)' % email)
                    return
            else:
                log.info('Shared-secret auth token does not match')
                return

            log.info('Successful SharedSecret with user: %s' % request.user.pk)
            return
        except Exception, e:
            log.info('Bad shared-secret auth data: %s (%s)', auth, e)
            return


class APITransactionMiddleware(TransactionMiddleware):
    """Wrap the transaction middleware so we can use it in the API only."""

    def process_request(self, request):
        if getattr(request, 'API', False):
            return (super(APITransactionMiddleware, self)
                    .process_request(request))

    def process_exception(self, request, exception):
        if getattr(request, 'API', False):
            return (super(APITransactionMiddleware, self)
                    .process_exception(request, exception))

    def process_response(self, request, response):
        if getattr(request, 'API', False):
            return (super(APITransactionMiddleware, self)
                    .process_response(request, response))
        return response


# How long to set the time-to-live on the cache.
PINNING_SECONDS = int(getattr(settings, 'MULTIDB_PINNING_SECONDS', 15))


class APIPinningMiddleware(PinningRouterMiddleware):
    """
    Similar to multidb, but we can't rely on cookies. Instead we cache the
    users who are to be pinned with a cache timeout. Users who are to be
    pinned are those that are not anonymous users and who are either making
    an updating request or who are already in our cache as having done one
    recently.

    If not in the API, will fall back to the cookie pinning middleware.

    Note: because the authentication process happens late when we are in the
    API, process_request() will be manually called from authentication classes
    when a user is successfully authenticated by one of those classes.
    """

    def cache_key(self, request):
        """Returns cache key based on user ID."""
        return u'api-pinning:%s' % request.amo_user.id

    def process_request(self, request):
        if not getattr(request, 'API', False):
            return super(APIPinningMiddleware, self).process_request(request)

        if (request.amo_user and not request.amo_user.is_anonymous() and
                (cache.get(self.cache_key(request)) or
                 request.method in ['DELETE', 'PATCH', 'POST', 'PUT'])):
            statsd.incr('api.db.pinned')
            pin_this_thread()
            return

        statsd.incr('api.db.unpinned')
        unpin_this_thread()

    def process_response(self, request, response):
        if not getattr(request, 'API', False):
            return (super(APIPinningMiddleware, self)
                    .process_response(request, response))

        response['API-Pinned'] = str(this_thread_is_pinned())

        if (request.amo_user and not request.amo_user.is_anonymous() and (
                request.method in ['DELETE', 'PATCH', 'POST', 'PUT'] or
                getattr(response, '_db_write', False))):
            cache.set(self.cache_key(request), 1, PINNING_SECONDS)

        return response


class CORSMiddleware(object):

    def process_response(self, request, response):
        # This is mostly for use by tastypie. Which doesn't really have a nice
        # hook for figuring out if a response should have the CORS headers on
        # it. That's because it will often error out with immediate HTTP
        # responses.
        fireplace_url = settings.FIREPLACE_URL
        fireplacey = request.META.get('HTTP_ORIGIN') == fireplace_url
        response['Access-Control-Allow-Headers'] = (
            'X-HTTP-Method-Override, Content-Type')

        if fireplacey or getattr(request, 'CORS', None):
            # If this is a request from our hosted frontend, allow cookies.
            if fireplacey:
                response['Access-Control-Allow-Origin'] = fireplace_url
                response['Access-Control-Allow-Credentials'] = 'true'
            else:
                response['Access-Control-Allow-Origin'] = '*'
            options = [h.upper() for h in request.CORS]
            if not 'OPTIONS' in options:
                options.append('OPTIONS')
            response['Access-Control-Allow-Methods'] = ', '.join(options)

        # The headers that the response will be able to access.
        response['Access-Control-Expose-Headers'] = (
            'API-Filter, API-Status, API-Version')

        return response

v_re = re.compile('^/api/v(?P<version>\d+)/|^/api/')


class APIVersionMiddleware(object):
    """
    Figures out what version of the API they are on. Maybe adds in a
    deprecation notice.
    """

    def process_request(self, request):
        if getattr(request, 'API', False):
            url = request.META.get('PATH_INFO', '')
            version = v_re.match(url).group('version')
            if not version:
                version = 1
            request.API_VERSION = int(version)

    def process_response(self, request, response):
        if not getattr(request, 'API', False):
            return response

        response['API-Version'] = request.API_VERSION
        if request.API_VERSION < settings.API_CURRENT_VERSION:
            response['API-Status'] = 'Deprecated'
        return response


class APIFilterMiddleware(object):
    """
    Add an API-Filter header containing a urlencoded string of filters applied
    to API requests.
    """
    def process_response(self, request, response):
        if getattr(request, 'API', False) and response.status_code < 500:
            devices = []
            for device in ('GAIA', 'MOBILE', 'TABLET'):
                if getattr(request, device, False):
                    devices.append(device.lower())
            filters = (
                ('carrier', get_carrier() or ''),
                ('device', devices),
                ('lang', request.LANG),
                ('pro', request.GET.get('pro', '')),
                ('region', request.REGION.slug),
            )
            response['API-Filter'] = urlencode(filters, doseq=True)
            patch_vary_headers(response, ['API-Filter'])
        return response


class TimingMiddleware(GraphiteRequestTimingMiddleware):
    """
    A wrapper around django_statsd timing middleware that sends different
    statsd pings if being used in API.
    """
    def process_view(self, request, *args):
        if getattr(request, 'API', False):
            TastyPieRequestTimingMiddleware().process_view(request, *args)
        else:
            super(TimingMiddleware, self).process_view(request, *args)

    def _record_time(self, request):
        pre = 'api' if getattr(request, 'API', False) else 'view'
        if hasattr(request, '_start_time'):
            ms = int((time.time() - request._start_time) * 1000)
            data = {'method': request.method,
                    'module': request._view_module,
                    'name': request._view_name,
                    'pre': pre}
            statsd.timing('{pre}.{module}.{name}.{method}'.format(**data), ms)
            statsd.timing('{pre}.{module}.{method}'.format(**data), ms)
            statsd.timing('{pre}.{method}'.format(**data), ms)
