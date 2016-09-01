import traceback

from django.conf import settings
from django.core.signals import got_request_exception

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context=None):
    """
    Custom exception handler for DRF, which ensures every exception we throw
    is caught, returned as a nice DRF Response, while still going to sentry
    etc.

    The default DRF exception handler does some of this work already, but it
    lets non-api exceptions through, and we don't want that.
    """
    # If propagate is true, bail early.
    if settings.DEBUG_PROPAGATE_EXCEPTIONS:
        raise

    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # If the response is None, then DRF didn't handle the exception and we
    # should do it ourselves.
    if response is None:
        # Start with a generic default error message.
        data = {'detail': 'Internal Server Error'}

        if settings.DEBUG:
            data['traceback'] = traceback.format_exc()

        # Send the got_request_exception signal so other apps like sentry
        # are aware of the exception. The sender does not match what a real
        # exception would do (we don't have access to the handler here) but it
        # should not be an issue, what matters is the request.
        request = context.get('request')
        sender = context.get('view').__class__
        got_request_exception.send(sender, request=request)

        # Send the 500 response back.
        response = Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return response
