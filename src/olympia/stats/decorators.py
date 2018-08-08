import functools

from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo import permissions
from olympia.addons.decorators import addon_view


def addon_view_stats(f):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        # Admins can see stats for every add-on regardless of its status.
        if acl.action_allowed(request, permissions.STATS_VIEW):
            qs = Addon.objects.all
        else:
            qs = Addon.objects.valid

        return addon_view(f, qs)(request, addon_id=addon_id, *args, **kw)
    return wrapper
