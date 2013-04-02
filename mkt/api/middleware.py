import re

from django.conf import settings
from django.middleware.transaction import TransactionMiddleware

from django_statsd.clients import statsd
from multidb.pinning import pin_this_thread, unpin_this_thread


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
            if set(['PATCH', 'POST', 'PUT']).intersection(set(options)):
                # We will be expecting JSON in the POST so expect Content-Type
                # to be set.
                response['Access-Control-Allow-Headers'] = 'Content-Type'
            response['Access-Control-Allow-Methods'] = ', '.join(options)
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
