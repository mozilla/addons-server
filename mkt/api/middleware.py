import re
import time
from urllib import urlencode

from django.conf import settings
from django.core.cache import cache
from django.middleware.transaction import TransactionMiddleware
from django.utils.cache import patch_vary_headers

from django_statsd.clients import statsd
from django_statsd.middleware import (GraphiteRequestTimingMiddleware,
                                      TastyPieRequestTimingMiddleware)
from multidb.pinning import (pin_this_thread, this_thread_is_pinned,
                             unpin_this_thread)
from multidb.middleware import PinningRouterMiddleware

from mkt.carriers import get_carrier


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
