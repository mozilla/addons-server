import re
from urllib import urlencode

from django.conf import settings
from django.middleware.transaction import TransactionMiddleware
from django.utils.cache import patch_vary_headers

from django_statsd.clients import statsd
from multidb.pinning import pin_this_thread, unpin_this_thread

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


class APIPinningMiddleware(object):
    """
    Similar to multidb, but we can't rely on cookies. Instead this will
    examine the request and pin to the master db if the user is authenticated.
    """

    def process_request(self, request):
        if not getattr(request, 'API', False):
            return

        if request.amo_user and not request.amo_user.is_anonymous():
            statsd.incr('api.db.pinned')
            pin_this_thread()
            return

        statsd.incr('api.db.unpinned')
        unpin_this_thread()


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
            'X-API-Filter, X-API-Status, X-API-Version')

        return response

v_re = re.compile('^/api/v(?P<version>\d+)/|^/api/')


class APIVersionMiddleware(object):
    """
    Figures out what version of the API they are on. Maybe adds in a
    deprecation notice.
    """

    def process_request(self, request):
        try:
            version = v_re.match(request.META['PATH_INFO']).group('version')
        except AttributeError:
            # Not in the API.
            return

        # If you are in the API, but don't have a version, this will be None.
        request.API_VERSION = version

    def process_response(self, request, response):
        # Not in the API.
        if not hasattr(request, 'API_VERSION'):
            return response

        response['X-API-Version'] = request.API_VERSION
        if not request.API_VERSION:
            response['X-API-Status'] = 'Deprecated'
        return response


class APIFilterMiddleware(object):
    """
    Add an X-API-Filter header containing a urlencoded string of filters applied
    to API requests.
    """
    def process_response(self, request, response):
        if getattr(request, 'API', False):
            filters = {
                'carrier': get_carrier() or '',
                'device': [],
                'lang': request.LANG,
                'region': request.REGION.slug
            }
            for device in ('GAIA', 'MOBILE', 'TABLET'):
                if getattr(request, device, False):
                    filters['device'].append(device.lower())
            response['X-API-Filter'] = urlencode(filters, doseq=True)
            patch_vary_headers(response, ['X-API-Filter'])
        return response
