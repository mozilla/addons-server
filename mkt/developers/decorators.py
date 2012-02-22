import functools

from django import http
from django.core.exceptions import ObjectDoesNotExist
import waffle

from amo.decorators import login_required
from access import acl
from addons.decorators import addon_view


def dev_required(owner_for_post=False, allow_editors=False, webapp=False,
                 skip_submit_check=False):
    """Requires user to be add-on owner or admin.

    When allow_editors is True, an editor can view the page.
    """
    def decorator(f):
        @addon_view
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            from mkt.developers.views import _resume
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
                if not skip_submit_check:
                    try:
                        # If it didn't go through the app submission
                        # checklist. Don't die. This will be useful for
                        # creating apps with an API later.
                        step = addon.appsubmissionchecklist.get_next()
                    except ObjectDoesNotExist:
                        step = None
                    # Redirect to the submit flow if they're not done.
                    if not getattr(f, 'submitting', False) and step:
                        return _resume(addon, step)
                return fun()
            return http.HttpResponseForbidden()
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
