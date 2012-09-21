import functools

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied

from amo.decorators import login_required
from access import acl
from addons.decorators import addon_view


def dev_required(owner_for_post=False, allow_editors=False, support=False,
                 webapp=False, skip_submit_check=False, staff=False):
    """Requires user to be add-on owner or admin.

    When allow_editors is True, an editor can view the page.

    When `staff` is True, users in the Staff or Support Staff groups are
    allowed. Users in the Developers group are allowed read-only.
    """
    def decorator(f):
        @addon_view
        @login_required
        @functools.wraps(f)
        def wrapper(request, addon, *args, **kw):
            from mkt.submit.views import _resume
            if webapp:
                kw['webapp'] = addon.is_webapp()
            fun = lambda: f(request, addon_id=addon.id, addon=addon,
                            *args, **kw)

            if allow_editors and acl.check_reviewer(request):
                return fun()

            if staff and (acl.action_allowed(request, 'Apps', 'Configure') or
                          acl.action_allowed(request, 'Apps',
                                             'ViewConfiguration')):
                return fun()

            if support:
                # Let developers and support people do their thangs.
                if (acl.check_addon_ownership(request, addon, support=True) or
                    acl.check_addon_ownership(request, addon, dev=True)):
                    return fun()
            else:
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
        return f(request, *args, webapp=True, **kwargs)
    return wrapper
