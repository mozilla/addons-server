import functools

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

import commonware.log
from addons.models import Addon

log = commonware.log.getLogger('mkt.purchase')


def addon_view(f, qs=Addon.objects.all):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, app_slug=None, *args, **kw):
        """Provides an addon given either an addon_id or app_slug."""
        assert addon_id or app_slug, 'Must provide addon_id or app_slug'
        get = lambda **kw: get_object_or_404(qs(), **kw)
        if addon_id and addon_id.isdigit():
            addon = get(id=addon_id)
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.slug != addon_id:
                url = request.path.replace(addon_id, addon.slug, 1)

                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)
        elif addon_id:
            addon = get(slug=addon_id)
        elif app_slug:
            addon = get(app_slug=app_slug)
        return f(request, addon, *args, **kw)
    return wrapper


def addon_view_factory(qs):
    # Don't evaluate qs or the locale will get stuck on whatever the server
    # starts with. The addon_view() decorator will call qs with no arguments
    # before doing anything, so lambdas are ok.
    # GOOD: Addon.objects.valid
    # GOOD: lambda: Addon.objects.valid().filter(type=1)
    # BAD: Addon.objects.valid()
    return functools.partial(addon_view, qs=qs)
