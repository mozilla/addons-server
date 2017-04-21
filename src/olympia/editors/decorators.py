import functools

from django.core.exceptions import PermissionDenied

from olympia import amo
from olympia.access import acl
from olympia.amo.decorators import login_required


def _view_on_get(request):
    """Return True if the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return (request.method == 'GET' and
            acl.action_allowed(request, amo.permissions.REVIEWER_TOOLS_VIEW))


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


def any_reviewer_required(f):
    """Require an addons or personas reviewer."""
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        try:
            return addons_reviewer_required(f)(request, *args, **kw)
        except PermissionDenied:
            return personas_reviewer_required(f)(request, *args, **kw)
    return wrapper
