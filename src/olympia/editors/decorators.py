import functools

from django.core.exceptions import PermissionDenied

from olympia.access import acl, permissions
from olympia.amo.decorators import login_required
from olympia.api.permissions import AllowReviewer


def _view_on_get(request):
    """Return True if the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return (request.method == 'GET' and
            acl.action_allowed(request, 'ReviewerTools', 'View'))


def addons_reviewer_required(f):
    """Require an addons reviewer user.

    The user logged in must be an addons reviewer or admin, or have the
    'ReviewerTools:View' permission for GET requests.

    An addons reviewer is someone who is in the group with the following
    permission: 'Addons:Review'.
    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if AllowReviewer().has_permission(request, None):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


unlisted_addons_reviewer_required = (
    permissions.ADDONS_REVIEW_UNLISTED.decorator)


def personas_reviewer_required(f):
    """Require an persona reviewer user.

    The user logged in must be a personas reviewer or admin, or have the
    'ReviewerTools:View' permission for GET requests.

    A personas reviewer is someone who is in the group with the following
    permission: 'Personas:Review'.

    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if (_view_on_get(request) or
                permissions.THEMES_REVIEW.has_permission(request)):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def any_reviewer_required(f):
    """Require an addons or personas reviewer."""
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        try:
            return addons_reviewer_required(f)(request, *args, **kw)
        except PermissionDenied:
            return personas_reviewer_required(f)(request, *args, **kw)
    return wrapper
