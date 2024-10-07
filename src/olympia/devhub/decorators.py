import functools

from django import http
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.shortcuts import redirect

import waffle

from olympia import amo
from olympia.access import acl
from olympia.accounts.decorators import two_factor_auth_required
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.amo.decorators import login_required
from olympia.devhub.utils import show_submissions_disabled_devhub
from olympia.versions.models import Version


def dev_required(
    owner_for_post=False,
    allow_reviewers_for_read=False,
    submitting=False,
    qs=Addon.objects.all,
):
    """Require user to be add-on owner or admin.

    When owner_for_post is True, only owners can make a POST request. That
    argument can also be a callable.

    When allow_reviewers_for_read is True, reviewers can view the page if the
    request is a HEAD or GET, provided that a file_id is also passed as keyword
    argument (so the channel can be checked to determine whether the reviewer
    has access).

    When submitting is True, access is not allowed if the add-on is a site
    permission add-on, regardless of other arguments. When it's False,
    attempting to access the decorated view with an incomplete add-on that has
    a listed version will redirect to the submit details step to complete
    metadata required for listed submission.

    Any non-allowed case will raise a PermissionDenied.
    """

    def decorator(f):
        @addon_view_factory(qs=qs)
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            def fun():
                return f(request, *args, **{'addon_id': addon.id, 'addon': addon, **kw})

            if request.method in ('HEAD', 'GET'):
                # Allow reviewers for read operations, if file_id is present
                # and the reviewer is the right kind of reviewer for this file.
                if allow_reviewers_for_read:
                    file_id = kw.get('file_id')
                    if file_id:
                        is_unlisted = Version.unfiltered.filter(
                            file__id=file_id, channel=amo.CHANNEL_UNLISTED
                        ).exists()
                        has_required_permission = (
                            acl.is_unlisted_addons_viewer_or_reviewer(request.user)
                            if is_unlisted
                            else (acl.is_listed_addons_viewer_or_reviewer(request.user))
                        )
                        if has_required_permission:
                            return fun()
                    else:
                        raise ImproperlyConfigured

                # On read-only requests, we can allow developers, and even let
                # authors see mozilla disabled add-ons.
                if acl.check_addon_ownership(
                    request.user,
                    addon,
                    allow_developer=True,
                    allow_mozilla_disabled_addon=True,
                ):
                    # Redirect to the submit flow if they're not done with
                    # listed submission.
                    if not submitting and addon.should_redirect_to_submit_flow():
                        return redirect('devhub.submit.details', addon.slug)
                    return fun()
            # Require an owner or deveveloper for POST requests (if the add-on
            # status is disabled that check will return False).
            elif request.method == 'POST':
                if acl.check_addon_ownership(
                    request.user,
                    addon,
                    allow_developer=not owner_for_post,
                ):
                    return fun()
            raise PermissionDenied

        return wrapper

    # The arg will be a function if they didn't pass owner_for_post.
    if callable(owner_for_post):
        f = owner_for_post
        owner_for_post = False
        return decorator(f)
    else:
        return decorator


def no_admin_disabled(f):
    """Require the addon not be STATUS_DISABLED (mozilla admin disabled)."""

    @functools.wraps(f)
    def wrapper(*args, **kw):
        addon = kw.get('addon')
        if addon and addon.status == amo.STATUS_DISABLED:
            raise http.Http404()
        return f(*args, **kw)

    return wrapper


def two_factor_auth_required_if_non_theme(f):
    """Require the user to be authenticated and have 2FA enabled but only if
    the addon passed to the function is not a theme.

    Needs to be applied after @dev_required or similar decorator that ensures
    the addon is passed as a keyword argument to the decorated function."""

    @functools.wraps(f)
    def wrapper(*args, **kw):
        addon = kw.get('addon')
        if addon and addon.type == amo.ADDON_STATICTHEME:
            return f(*args, **kw)
        return two_factor_auth_required(f)(*args, **kw)

    return wrapper


def require_submissions_enabled_devhub(f):
    """Require the enable-submissions waffle flag to be enabled."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if waffle.flag_is_active(request, 'enable-submissions'):
            return f(request, *args, **kw)
        return show_submissions_disabled_devhub(request)

    return wrapper
