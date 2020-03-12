import functools

from django.core.exceptions import PermissionDenied

from olympia.access import acl
from olympia.amo.decorators import login_required
from olympia.constants import permissions


def _view_on_get(request):
    """Return True if the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return (request.method == 'GET' and
            acl.action_allowed(request, permissions.REVIEWER_TOOLS_VIEW))


def permission_or_tools_view_required(permission):
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(request, *args, **kw):
            view_on_get = _view_on_get(request)
            if view_on_get or acl.action_allowed(request, permission):
                return f(request, *args, **kw)
            else:
                raise PermissionDenied
        return wrapper
    return decorator


def unlisted_addons_reviewer_required(f):
    """Require an "unlisted addons" reviewer user.

    The user logged in must be an unlisted addons reviewer or admin.

    An unlisted addons reviewer is someone who is in a group with the following
    permission: 'Addons:ReviewUnlisted'.
    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if acl.check_unlisted_addons_reviewer(request):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def any_reviewer_required(f):
    """Require any kind of reviewer. Use only for views that don't alter data
    but just provide a generic reviewer-related page, such as the reviewer
    dashboard.

    Allows access to users with any of those permissions:
    - ReviewerTools:View (for GET requests only)
    - Addons:Review
    - Addons:ReviewUnlisted
    - Addons:ContentReview
    - Addons:PostReview
    - Addons:ThemeReview
    - Addons:RecommendedReview
    """
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if acl.is_user_any_kind_of_reviewer(
                request.user, allow_viewers=(request.method == 'GET')):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def any_reviewer_or_moderator_required(f):
    """Like @any_reviewer_required, but allows users with Ratings:Moderate
    as well."""
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        allow_access = (
            acl.is_user_any_kind_of_reviewer(
                request.user, allow_viewers=(request.method == 'GET')) or
            acl.action_allowed(request, permissions.RATINGS_MODERATE))
        if allow_access:
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper
