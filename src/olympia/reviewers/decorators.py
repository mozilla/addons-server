import functools

from django.core.exceptions import PermissionDenied

from olympia.amo import permissions
from olympia.access import acl
from olympia.amo.decorators import login_required


def _view_on_get(request):
    """Return True if the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return (request.method == 'GET' and
            acl.action_allowed(request, permissions.REVIEWER_TOOLS_VIEW))


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
        if _view_on_get(request) or acl.check_addons_reviewer(request):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


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
        if _view_on_get(request) or acl.check_personas_reviewer(request):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def ratings_moderator_required(f):
    """Require a ratings moderator user.

    The user logged in must be a ratings moderator or admin, or have the
    'ReviewerTools:View' permission for GET requests.

    A ratings moderator is someone who is in the group with the following
    permission: 'Ratings:Moderate'.

    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if _view_on_get(request) or acl.action_allowed(
                request, permissions.RATINGS_MODERATE):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def any_reviewer_required(f):
    """Require any kind of reviewer. Use only for views that don't alter data
    but just provide a generic reviewer-related page, such as the reviewer
    dashboard.

    Allows access to users with any of those permissions:
    - ReviewerTools:View
    - Addons:Review
    - Addons:ReviewUnlisted
    - Addons:ContentReview
    - Addons:PostReview
    - Personas:Review
    """
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        allow_access = (
            acl.action_allowed(request, permissions.REVIEWER_TOOLS_VIEW) or
            acl.action_allowed(request, permissions.ADDONS_REVIEW) or
            acl.action_allowed(request, permissions.ADDONS_REVIEW_UNLISTED) or
            acl.action_allowed(request, permissions.ADDONS_CONTENT_REVIEW) or
            acl.action_allowed(request, permissions.ADDONS_POST_REVIEW) or
            acl.action_allowed(request, permissions.THEMES_REVIEW))
        if allow_access:
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper
