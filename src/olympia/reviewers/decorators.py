import functools

from django.core.exceptions import PermissionDenied

from olympia.access import acl
from olympia.amo.decorators import login_required
from olympia.constants import permissions


def _view_on_get(request, permission):
    """Return True if the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return request.method == 'GET' and acl.action_allowed(request, permission)


def permission_or_tools_listed_view_required(permission):
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            view_on_get = _view_on_get(request, permissions.REVIEWER_TOOLS_VIEW)
            if view_on_get or acl.action_allowed(request, permission):
                return f(request, *args, **kw)
            else:
                raise PermissionDenied

        return wrapper

    return decorator


def permission_or_tools_unlisted_view_required(permission):
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            view_on_get = _view_on_get(
                request, permissions.REVIEWER_TOOLS_UNLISTED_VIEW
            )
            if view_on_get or acl.action_allowed(request, permission):
                return f(request, *args, **kw)
            else:
                raise PermissionDenied

        return wrapper

    return decorator


def any_reviewer_required(f):
    """Require any kind of reviewer. Use only for views that don't alter data
    but just provide a generic reviewer-related page, such as the reviewer
    dashboard.

    Allows access to users with any of those permissions:
    - ReviewerTools:View (for GET requests only)
    - ReviewerTools:ViewUnlisted (for GET requests only)
    - Addons:Review
    - Addons:ReviewUnlisted
    - Addons:ContentReview
    - Addons:ThemeReview
    - Addons:RecommendedReview
    """

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if acl.is_user_any_kind_of_reviewer(
            request.user, allow_viewers=(request.method == 'GET')
        ):
            return f(request, *args, **kw)
        raise PermissionDenied

    return wrapper


def any_reviewer_or_moderator_required(f):
    """Like @any_reviewer_required, but allows users with Ratings:Moderate
    as well."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        allow_access = acl.is_user_any_kind_of_reviewer(
            request.user, allow_viewers=(request.method == 'GET')
        ) or acl.action_allowed(request, permissions.RATINGS_MODERATE)
        if allow_access:
            return f(request, *args, **kw)
        raise PermissionDenied

    return wrapper
