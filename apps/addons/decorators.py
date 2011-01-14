import functools

from django import http
from django.shortcuts import get_object_or_404

from addons.models import Addon


def addon_view(f, qs=Addon.objects.all):
    def wrapper(request, addon_id, *args, **kw):
        get = lambda **kw: get_object_or_404(qs(), **kw)
        if addon_id.isdigit():
            addon = get(id=addon_id)
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.slug != addon_id:
                url = request.path.replace(addon_id, addon.slug)
                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)
        else:
            addon = get(slug=addon_id)
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
