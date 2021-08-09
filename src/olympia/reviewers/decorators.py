import functools

from urllib.parse import quote

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from olympia.access import acl
from olympia.addons.decorators import owner_or_unlisted_viewer_or_reviewer
from olympia.addons.models import Addon
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


def reviewer_addon_view(f):
    """A view decorator for reviewers. The AMO add-on ID is the canonical identifier.
    Passing the Add-on GUID or slug will redirect to the page using the ID."""

    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        """Provides an addon instance to the view given addon_id, which can be
        an Addon pk, guid or a slug."""
        assert addon_id, 'Must provide addon id, guid or slug'

        qs = Addon.unfiltered.all

        lookup_field = Addon.get_lookup_field(addon_id)
        if lookup_field == 'pk':
            addon = get_object_or_404(qs(), pk=addon_id)
        else:
            addon = get_object_or_404(qs(), **{lookup_field: addon_id})
            # FIXME: what about a slug called 'addon' ? And are we sure that
            # request.path will always already be quoted ? If not that would
            # break the redirect.
            # Maybe instead resolve() it and replace the first parameter with
            # addon.pk, then reverse() the url ?
            url = request.path.replace(quote(addon_id), str(addon.pk), 1)
            if request.GET:
                url += '?' + request.GET.urlencode()
            return http.HttpResponsePermanentRedirect(url)

        return f(request, addon, *args, **kw)

    return wrapper


def reviewer_addon_view_factory(f):
    decorator = functools.partial(reviewer_addon_view)
    return decorator(f)
