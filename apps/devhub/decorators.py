import functools

from django import http
from django.core.exceptions import PermissionDenied

from amo.decorators import login_required
from access import acl
from addons.decorators import addon_view_factory
from addons.models import Addon
from devhub.models import SubmitStep


def dev_required(owner_for_post=False, allow_editors=False, theme=False):
    """Requires user to be add-on owner or admin.

    When allow_editors is True, an editor can view the page.
    """
    def decorator(f):
        @addon_view_factory(qs=Addon.with_unlisted.all)
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            from devhub.views import _resume
            if theme:
                kw['theme'] = addon.is_persona()
            elif addon.is_persona():
                # Don't allow theme views if theme not passed in.
                raise http.Http404

            def fun():
                return f(request, addon_id=addon.id, addon=addon, *args, **kw)

            if allow_editors:
                if acl.is_editor(request, addon):
                    return fun()
            # Require an owner or dev for POST requests.
            if request.method == 'POST':
                if acl.check_addon_ownership(request, addon,
                                             dev=not owner_for_post):
                    return fun()
            # Ignore disabled so they can view their add-on.
            elif acl.check_addon_ownership(request, addon, viewer=True,
                                           ignore_disabled=True):
                step = SubmitStep.objects.filter(addon=addon)
                # Redirect to the submit flow if they're not done.
                if not getattr(f, 'submitting', False) and step:
                    return _resume(addon, step)
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
