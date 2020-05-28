import traceback

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.signals import got_request_exception
from django.http import Http404

from rest_framework import exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import set_rollback


def custom_exception_handler(exc, context=None):
    """
    Custom exception handler for DRF, which ensures every exception we throw
    is caught, returned as a nice DRF Response, while still going to sentry
    etc.

    This is mostly copied from DRF exception handler, with the following
    changes/additions:
    - A condition preventing set_rollback() from being called in some cases
      where we know there might be something to record in the database
    - Handling of non-API exceptions, returning an 500 error that looks like an
      API response, while still logging things to Sentry.
    """
    # If propagate is true, bail early.
    if settings.DEBUG_PROPAGATE_EXCEPTIONS:
        raise

    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    if isinstance(exc, exceptions.APIException):
        headers = {}
        if getattr(exc, 'auth_header', None):
            headers['WWW-Authenticate'] = exc.auth_header
        if getattr(exc, 'wait', None):
            headers['Retry-After'] = '%d' % exc.wait

        if isinstance(exc.detail, (list, dict)):
            data = exc.detail
            code_or_codes = exc.get_codes()
        else:
            data = {'detail': exc.detail}
            code_or_codes = exc.get_codes()

        # If it's not a throttled/permission denied coming from a restriction,
        # we can roll the current transaction back. Otherwise don't, we may
        # need to record something in the database.
        # Note: `code_or_codes` can be a string, or a list of strings, or even
        # a dict of strings here, depending on what happened. Fortunately the
        # only thing we care about is the most basic case, a string, we don't
        # need to test for the rest.
        if (not isinstance(exc, exceptions.Throttled) and
            not (isinstance(exc, exceptions.PermissionDenied) and
                 code_or_codes == 'permission_denied_restriction')):
            set_rollback()
        return Response(data, status=exc.status_code, headers=headers)
    else:
        # Not a DRF exception, we want to return an APIfied 500 error while
        # still logging it to Sentry.
        data = base_500_data()

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


def base_500_data():
    # Start with a generic default error message.
    data = {'detail': 'Internal Server Error'}

    if settings.DEBUG:
        data['traceback'] = traceback.format_exc()
    return data
