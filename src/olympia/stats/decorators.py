import functools

from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo import permissions
from olympia.addons.decorators import addon_view


def addon_view_stats(f):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        """Provides an addon instance to the view given addon_id, which can be
        an Addon pk or a slug."""
        assert addon_id, 'Must provide addon id or slug'

        if acl.action_allowed(request, permissions.STATS_VIEW):
            qs = Addon.objects.all
        else:
            qs = Addon.objects.valid

        return addon_view(f, qs)(request, addon_id=addon_id, *args, **kw)
    return wrapper
