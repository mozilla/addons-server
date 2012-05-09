import functools

from django import http

from access.acl import action_allowed
from amo.decorators import login_required


def admin_ish_required(f):
    """Admin, or someone with AdminTools:View, required."""
    @functools.wraps(f)
    @login_required
    def wrapper(request, *args, **kw):
        if (action_allowed(request, 'Admin', '%') or
            action_allowed(request, 'AdminTools', 'View')):
            return f(request, *args, **kw)
        return http.HttpResponseForbidden()
    return wrapper
