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
    return request.method == 'GET' and acl.action_allowed(
        request, permissions.REVIEWER_TOOLS_VIEW
    )


def legacy_addons_or_themes_reviewer_required(f):
    """Require a legacy reviewer or static themes reviewer user.

    The user logged in must be an addons reviewer or admin, or have the
    'ReviewerTools:View' permission for GET requests.

    A legacy addons reviewer is someone who is in the group with the following
    permission: 'Addons:Review';
    a static themes reviewer is someone who is in the group with the following
    permission: 'Addons:ThemeReview'
    """

    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if (
            _view_on_get(request)
            or acl.action_allowed(request, permissions.ADDONS_REVIEW)
            or acl.check_static_theme_reviewer(request)
        ):
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
            request, permissions.RATINGS_MODERATE
        ):
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
    - Addons:ThemeReview
    """

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if acl.is_user_any_kind_of_reviewer(request.user):
            return f(request, *args, **kw)
        raise PermissionDenied

    return wrapper


def any_reviewer_or_moderator_required(f):
    """Like @any_reviewer_required, but allows users with Ratings:Moderate
    as well."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        allow_access = acl.is_user_any_kind_of_reviewer(
            request.user
        ) or acl.action_allowed(request, permissions.RATINGS_MODERATE)
        if allow_access:
            return f(request, *args, **kw)
        raise PermissionDenied

    return wrapper
