import functools

from django.core.exceptions import PermissionDenied

from access import acl
from amo.decorators import login_required


def _view_on_get(request):
    """Returns whether the user can access this page.

    If the user is in a group with rule 'ReviewerTools:View' and the request is
    a GET request, they are allowed to view.
    """
    return (request.method == 'GET' and
            acl.action_allowed(request, 'ReviewerTools', 'View'))


def addons_reviewer_required(f):
    """Requires the user to be logged in as an addons reviewer or admin, or
    allows someone with rule 'ReviewerTools:View' for GET requests.

    An addons reviewer is someone who is in the group with the following
    permission: Addons:Review.

    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if _view_on_get(request) or acl.check_addons_reviewer(request):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def personas_reviewer_required(f):
    """Requires the user to be logged in as a personas reviewer or admin, or
    allows someone with rule 'ReviewerTools:View' for GET requests.

    A personas reviewer is someone who is in the group with the following
    permission: Personas:Review.

    """
    @login_required
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if _view_on_get(request) or acl.check_personas_reviewer(request):
            return f(request, *args, **kw)
        raise PermissionDenied
    return wrapper


def any_reviewer_required(f):
    """Return a decorator that is an OR between addons_reviewer_required and
    personas_reviewer_required.

    This means that this decorators requires that the reviewer is either an
    addons reviewer or a personas reviewer.

    """
    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        try:
            return addons_reviewer_required(f)(request, *args, **kw)
        except PermissionDenied:
            return personas_reviewer_required(f)(request, *args, **kw)
    return wrapper
