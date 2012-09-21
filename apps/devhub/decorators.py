import functools

from django.core.exceptions import PermissionDenied

import waffle

from amo.decorators import login_required
from access import acl
from addons.decorators import addon_view
from devhub.models import SubmitStep


def dev_required(owner_for_post=False, allow_editors=False, webapp=False):
    """Requires user to be add-on owner or admin.

    When allow_editors is True, an editor can view the page.
    """
    def decorator(f):
        @addon_view
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            from devhub.views import _resume
            if webapp:
                kw['webapp'] = addon.is_webapp()
            fun = lambda: f(request, addon_id=addon.id, addon=addon,
                            *args, **kw)
            if allow_editors:
                if acl.check_reviewer(request):
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


# Mark a view as a web app
def use_apps(f):
    def wrapper(request, *args, **kwargs):
        # This should be set to True when the waffle
        # flag is removed!
        show_webapp = waffle.flag_is_active(request, 'accept-webapps')
        return f(request, *args, webapp=show_webapp, **kwargs)
    return wrapper
