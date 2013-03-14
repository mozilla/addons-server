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

        fireplacey = request.META.get('HTTP_ORIGIN') == settings.FIREPLACE_URL
        if fireplacey or getattr(request, 'CORS', None):
            # If this is a request from our hosted frontend, allow cookies.
            if fireplacey:
                response['Access-Control-Allow-Origin'] = settings.FIREPLACE_URL
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
