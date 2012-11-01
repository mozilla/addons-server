import functools
import json
import types

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils.http import urlquote

import commonware.log

from . import models as context
from .urlresolvers import reverse
from .utils import JSONEncoder

from amo import get_user, set_user
from users.utils import get_task_user


task_log = commonware.log.getLogger('z.task')


def login_required(f=None, redirect=True):
    """
    Like Django's login_required, but with to= instead of next=.

    If redirect=False then we return 401 instead of redirecting to the
    login page.  That's nice for ajax views.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kw):
            if request.user.is_authenticated():
                return func(request, *args, **kw)
            else:
                if redirect:
                    url = reverse('users.login')
                    path = urlquote(request.get_full_path())
                    return http.HttpResponseRedirect('%s?to=%s' % (url, path))
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


def permission_required(app, action):
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            from access import acl
            if acl.action_allowed(request, app, action):
                return f(request, *args, **kw)
            else:
                raise PermissionDenied
        return wrapper
    return decorator


def any_permission_required(pairs):
    """
    If any permission passes, call the function. Otherwise raise 403.
    """
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            from access import acl
            for app, action in pairs:
                if acl.action_allowed(request, app, action):
                    return f(request, *args, **kw)
            raise PermissionDenied
        return wrapper
    return decorator


def restricted_content(f):
    """
    Prevent access to a view function for accounts restricted from
    posting user-generated content.
    """
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        from access import acl
        if (acl.action_allowed(request, '*', '*')
            or not acl.action_allowed(request, 'Restricted', 'UGC')):
            return f(request, *args, **kw)
        else:
            raise PermissionDenied
    return wrapper


def modal_view(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        response = f(*args, modal=True, **kw)
        return response
    return wrapper


def json_response(response, has_trans=False, status_code=200):
    """
    Return a response as JSON. If you are just wrapping a view,
    then use the json_view decorator.
    """
    if has_trans:
        response = json.dumps(response, cls=JSONEncoder)
    else:
        response = json.dumps(response)
    return http.HttpResponse(response,
                             content_type='application/json',
                             status=status_code)


def json_view(f=None, has_trans=False, status_code=200):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            response = func(*args, **kw)
            if isinstance(response, http.HttpResponse):
                return response
            else:
                return json_response(response, has_trans=has_trans,
                                     status_code=status_code)
        return wrapper
    if f:
        return decorator(f)
    else:
        return decorator


json_view.error = lambda s: http.HttpResponseBadRequest(
    json.dumps(s), content_type='application/json')


def skip_cache(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        with context.skip_cache():
            return f(*args, **kw)
    return wrapper


def use_master(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        with context.use_master():
            return f(*args, **kw)
    return wrapper


def write(f):
    return use_master(skip_cache(f))


def set_modified_on(f):
    """
    Will update the modified timestamp on the provided objects
    when the wrapped function exits sucessfully (returns True).
    Looks up objects defined in the set_modified_on kwarg.
    """
    from amo.tasks import set_modified_on_object

    @functools.wraps(f)
    def wrapper(*args, **kw):
        objs = kw.pop('set_modified_on', None)
        result = f(*args, **kw)
        if objs and result:
            for obj in objs:
                task_log.info('Delaying setting modified on object: %s, %s' %
                              (obj.__class__.__name__, obj.pk))
                set_modified_on_object.apply_async(
                                            args=[obj], kwargs=None,
                                            countdown=settings.MODIFIED_DELAY)
        return result
    return wrapper


def no_login_required(f):
    """
    If you are using the LoginRequiredMiddleware mark this view
    as not needing any sort of login.
    """
    f._no_login_required = True
    return f


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


def set_task_user(f):
    """Sets the user to be the task user, then unsets it."""
    @functools.wraps(f)
    def wrapper(*args, **kw):
        old_user = get_user()
        set_user(get_task_user())
        try:
            result = f(*args, **kw)
        finally:
            set_user(old_user)
        return result
    return wrapper


def bust_fragments_on_post(url_prefix, bust_on_2xx=True, bust_on_3xx=True):
    """
    Set a cookie to bust the fragment cache for a specific URL prefix.

    `url_prefix`
        The URL prefix to set the cache-busting flag for. This can be a string
        or a list of strings.
    `bust_on_2xx`
        If True (default), the cookie will be set when the page response is a
        200.
    `bust_on_3xx`
        If True (default), the cookie will be set when the page response is a
        300.
    """

    if isinstance(url_prefix, types.StringTypes):
        url_prefix = [url_prefix]
    prefix = json.dumps(url_prefix)

    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kwargs):
            response = f(request, *args, **kwargs)

            # This function only bust
            if request.method != 'POST':
                return response

            status_code = response.status_code
            status_code -= status_code % 100
            # Ignore status codes that we don't plan on busting for.
            if (status_code not in (200, 300, ) or
                status_code == 200 and not bust_on_2xx or
                status_code == 300 and not bust_on_3xx):
                return response

            # At this point, we know we're busting the fragment cache.
            response.set_cookie('fcbust', prefix)

            return response
        return wrapper
    return decorator
