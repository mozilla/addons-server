import functools

from django.core.exceptions import PermissionDenied

from olympia import amo
from olympia.access.acl import action_allowed
from olympia.amo.decorators import login_required


def admin_required(f):
    """
    Decorator to apply to views that require an admin to access.
    """

    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if action_allowed(request, amo.permissions.ADMIN_TOOLS):
            return f(request, *args, **kw)
        raise PermissionDenied

    return wrapper
