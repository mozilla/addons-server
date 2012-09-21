import functools

from django.core.exceptions import PermissionDenied

from access.acl import action_allowed
from amo.decorators import login_required


def admin_required(reviewers=False):
    """
    Admin, or someone with AdminTools:View, required.

    If reviewers=True, ReviewerAdminTools:View is allowed also.
    """
    def decorator(f):
        @login_required
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            admin = (action_allowed(request, 'Admin', '%') or
                     action_allowed(request, 'AdminTools', 'View'))
            if reviewers == True:
                admin = (admin or
                         action_allowed(request, 'ReviewerAdminTools', 'View'))
            if admin:
                return f(request, *args, **kw)
            raise PermissionDenied
        return wrapper
    # If decorator has no args, and is "paren-less", it's callable.
    if callable(reviewers):
        return decorator(reviewers)
    else:
        return decorator
