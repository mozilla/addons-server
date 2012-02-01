import functools
import json

import commonware.log

from django import http
from django.conf import settings
from django.utils.http import urlquote

from . import models as context
from .urlresolvers import reverse

import redisutils

task_log = commonware.log.getLogger('z.task')

from amo.utils import JSONEncoder


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
        def wrapper(request, *args, **kw):
            from access import acl
            if acl.action_allowed(request, app, action):
                return f(request, *args, **kw)
            else:
                return http.HttpResponseForbidden()
        return wrapper
    return decorator


def modal_view(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        response = f(*args, modal=True, **kw)
        return response
    return wrapper


def json_view(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        response = f(*args, **kw)
        if isinstance(response, http.HttpResponse):
            return response
        else:
            return http.HttpResponse(json.dumps(response),
                                     content_type='application/json')
    return wrapper


# a version of json_view that understands translated strings.
def happy_json_view(f):
    @functools.wraps(f)
    def wrapper(*args, **kw):
        response = f(*args, **kw)
        if isinstance(response, http.HttpResponse):
            return response
        else:
            return http.HttpResponse(json.dumps(response, cls=JSONEncoder),
                                     content_type='application/json')
    return wrapper


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


def redis(f):
    """Adds a redis connection as an argument to the method."""
    @functools.wraps(f)
    def wrapper(*args, **kw):
        redis = redisutils.connections['master']
        return f(redis, *args, **kw)
    return wrapper
