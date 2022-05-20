import datetime
import functools
import json

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied

from rest_framework import exceptions as drf_exceptions
from rest_framework.settings import api_settings

import olympia.core.logger

from . import models as context


task_log = olympia.core.logger.getLogger('z.task')


def login_required(f=None, redirect=True):
    """
    Like Django's login_required, but with to= instead of next=.

    If redirect=False then we return 401 instead of redirecting to the
    login page.  That's nice for ajax views.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kw):
            # Prevent circular ref in accounts.utils
            from olympia.accounts.utils import redirect_for_login

            if request.user.is_authenticated:
                return func(request, *args, **kw)
            else:
                if redirect:
                    return redirect_for_login(request)
                else:
                    return http.HttpResponse(status=401)

        return wrapper

    if f:
        return decorator(f)
    else:
        return decorator


def post_required(f):
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])
        else:
            return f(request, *args, **kw)

    return wrapper


def permission_required(permission):
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            from olympia.access import acl

            if acl.action_allowed_for(request.user, permission):
                return f(request, *args, **kw)
            else:
                raise PermissionDenied

        return wrapper

    return decorator


def json_response(response, has_trans=False, status_code=200):
    """
    Return a response as JSON. If you are just wrapping a view,
    then use the json_view decorator.
    """
    # to avoid circular imports with users.models
    from .utils import AMOJSONEncoder

    if has_trans:
        response = json.dumps(response, cls=AMOJSONEncoder)
    else:
        response = json.dumps(response)
    return http.HttpResponse(
        response, content_type='application/json', status=status_code
    )


def json_view(f=None, has_trans=False, status_code=200):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            response = func(*args, **kw)
            if isinstance(response, http.HttpResponse):
                return response
            else:
                return json_response(
                    response, has_trans=has_trans, status_code=status_code
                )

        return wrapper

    if f:
        return decorator(f)
    else:
        return decorator


json_view.error = lambda s: http.HttpResponseBadRequest(
    json.dumps(s), content_type='application/json'
)


def use_primary_db(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        with context.use_primary_db():
            return f(*args, **kw)

    return wrapper


def set_modified_on(f):
    """
    Will update the modified timestamp on the objects provided through
    the `set_modified_on` keyword argument, a short time after the wrapped
    function exits successfully (returns a truthy value).

    If that function returns a dict, it will also use that dict as additional
    keyword arguments to update on the provided objects.
    """
    from olympia.amo.tasks import set_modified_on_object

    @functools.wraps(f)
    def wrapper(*args, **kw):
        obj_info = kw.pop('set_modified_on', None)
        # obj_info is a tuple in the form of (app_label, model_name, pk)
        result = f(*args, **kw)
        if obj_info and result:
            # If the function returned a dict, pass that dict down as
            # kwargs to the set_modified_on_object task. Useful to set
            # things like icon hashes.
            kwargs_from_result = result if isinstance(result, dict) else {}
            task_log.info(
                'Delaying setting modified on object: %s, %s'
                % (obj_info[0], obj_info[1])
            )
            # Execute set_modified_on_object in NFS_LAG_DELAY seconds. This
            # allows us to make sure any changes have been written to disk
            # before changing modification date and/or image hashes stored
            # on objects - otherwise we could end up caching an old version
            # of an image on CDNs/clients for a very long time.
            set_modified_on_object.apply_async(
                args=obj_info,
                kwargs=kwargs_from_result,
                eta=(
                    datetime.datetime.now()
                    + datetime.timedelta(seconds=settings.NFS_LAG_DELAY)
                ),
            )
        return result

    return wrapper


def allow_cross_site_request(f):
    """Allow other sites to access this resource, see
    https://developer.mozilla.org/en/HTTP_access_control."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        response = f(request, *args, **kw)
        """If Access-Control-Allow-Credentials isn't set, the browser won't
        return data required cookies to see.  This is a good thing, let's keep
        it that way."""
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET'
        return response

    return wrapper


def api_authentication(f):
    """Allows API authentication to be used by this django view. Standard auth will
    already have been attempted by this point so api auth will only be tried for
    anonymous (unauthenticated) requests."""

    from olympia.api.authentication import (
        get_authorization_header,
        SessionIDAuthentication,
        JWTKeyAuthentication,
    )

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if request.user.is_anonymous and get_authorization_header(request):
            # if user isn't authenticated with standard auth, try the API auth methods
            try:
                for api_auth in (SessionIDAuthentication, JWTKeyAuthentication):
                    api_auth = api_auth()
                    result = api_auth.authenticate(request)
                    if result:
                        request.user, _ = result
                        break
            except drf_exceptions.AuthenticationFailed as exc:
                # We have to set some props DRF would usually set in the APIView
                exc.auth_header = api_auth.authenticate_header(request)
                response = api_settings.EXCEPTION_HANDLER(exc, None)
                response.accepted_renderer = api_settings.DEFAULT_RENDERER_CLASSES[0]()
                response.accepted_media_type = response.accepted_renderer.media_type
                response.renderer_context = {
                    'view': None,
                    'args': args,
                    'kwargs': kw,
                    'request': request,
                }
                return response

        return f(request, *args, **kw)

    return wrapper
