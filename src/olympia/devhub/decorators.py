import functools

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.amo.decorators import login_required
from olympia.constants import permissions


def dev_required(owner_for_post=False, allow_reviewers_for_read=False,
                 submitting=False, qs=Addon.objects.all):
    """Requires user to be add-on owner or admin.

    When allow_reviewers is True, reviewers can view the page.
    """
    def decorator(f):
        @addon_view_factory(qs=qs)
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            def fun():
                return f(request, addon_id=addon.id, addon=addon, *args, **kw)

            if request.method in ('HEAD', 'GET'):
                # Allow reviewers for read operations.
                if allow_reviewers_for_read and (
                    acl.is_reviewer(request, addon) or acl.action_allowed(
                        request, permissions.REVIEWER_TOOLS_VIEW)):
                    return fun()
                # On read-only requests, ignore disabled so developers can
                # still view their add-on.
                if acl.check_addon_ownership(request, addon, dev=True,
                                             ignore_disabled=True):
                    # Redirect to the submit flow if they're not done.
                    if (not submitting and
                            addon.should_redirect_to_submit_flow()):
                        return redirect('devhub.submit.details', addon.slug)
                    return fun()
            # Require an owner or dev for POST requests (if the add-on status
            # is disabled that check will return False).
            elif request.method == 'POST':
                if acl.check_addon_ownership(
                        request, addon, dev=not owner_for_post):
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
    """Requires the addon not be STATUS_DISABLED (mozilla admin disabled)."""
    @functools.wraps(f)
    def wrapper(*args, **kw):
        addon = kw.get('addon')
        if addon and addon.status == amo.STATUS_DISABLED:
            raise http.Http404()
        return f(*args, **kw)
    return wrapper
