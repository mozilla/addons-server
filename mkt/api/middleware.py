from functools import wraps

from django.middleware.transaction import TransactionMiddleware


class APIOnlyMiddleware(object):
    """
    This is a wrapper so that we can apply middleware to the API only, rather
    than the entire site. You can use this to wrap any existing middleware
    and it will only be used when request.API is set.

    request.API is currently set by the RedirectPrefixedURIMiddleware, which
    already does a lot of URL path examination. That middleware has to come
    before any middleware that uses this wrapper.
    """
    def __getattr__(self, attr):
        func = self.wrapped.__getattribute__(attr)
        if callable(func):
            @wraps(func)
            def wrapped(request, *args):
                if not request.API:
                    return
                return func(request, *args)
            return wrapped
        return func


class APITransactionMiddleware(APIOnlyMiddleware):
    """Wrap the transaction middleware so we can use it in the API only."""

    def __init__(self):
        self.wrapped = TransactionMiddleware()


class CORSMiddleware(object):

    def process_response(self, request, response):
        # This is mostly for use by tastypie. Which doesn't really have a nice
        # hook for figuring out if a response should have the CORS headers on
        # it. That's because it will often error out with immediate HTTP
        # responses.
        if getattr(request, 'CORS', None):
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
