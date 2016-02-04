import functools

from django.core.exceptions import PermissionDenied

from olympia.access.acl import action_allowed
from olympia.amo.decorators import login_required


def admin_required(reviewers=False, theme_reviewers=False):
    """
    Admin, or someone with AdminTools:View, required.

    If reviewers=True        ReviewerAdminTools:View is allowed also.
    If theme_reviewers=True  SeniorPersonasTools:View is allowed also.
    """
    def decorator(f):
        @login_required
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            admin = (action_allowed(request, 'Admin', '%') or
                     action_allowed(request, 'AdminTools', 'View'))
            # Yes, the "is True" is here on purpose... because this decorator
            # takes optional arguments, but doesn't do it properly (so if
            # you're not giving it arguments, it takes the decorated function
            # as the first argument, and then "reviewers" is truthy.
            if reviewers is True:
                admin = (
                    admin or
                    action_allowed(request, 'ReviewerAdminTools', 'View'))
            if theme_reviewers is True:
                admin = (
                    admin or
                    action_allowed(request, 'SeniorPersonasTools', 'View'))
            if admin:
                return f(request, *args, **kw)
            raise PermissionDenied
        return wrapper
    # If decorator has no args, and is "paren-less", it's callable.
    if callable(reviewers):
        return decorator(reviewers)
    else:
        return decorator
