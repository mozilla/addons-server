import contextlib
import functools
import json

from django import http
from django.contrib.auth import decorators as auth_decorators
from django.utils.http import urlquote

from . import models as context
from .urlresolvers import reverse


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
