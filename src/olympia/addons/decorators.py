import functools

from django import http
from django.shortcuts import get_object_or_404

from olympia.access import acl
from olympia.addons.models import Addon


def owner_or_unlisted_reviewer(request, addon):
    return (acl.check_unlisted_addons_reviewer(request) or
            # We don't want "admins" here, because it includes anyone with the
            # "Addons:Edit" perm, we only want those with
            # "Addons:ReviewUnlisted" perm (which is checked above).
            acl.check_addon_ownership(request, addon, admin=False, dev=True))


def addon_view(f, qs=Addon.objects.all):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        """Provides an addon instance to the view given addon_id, which can be
        an Addon pk or a slug."""
        assert addon_id, 'Must provide addon id or slug'

        if addon_id and addon_id.isdigit():
            addon = get_object_or_404(qs(), id=addon_id)
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.slug and addon.slug != addon_id:
                url = request.path.replace(addon_id, addon.slug, 1)

                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)
        else:
            addon = get_object_or_404(qs(), slug=addon_id)
        # If the addon is unlisted it needs either an owner/viewer/dev/support,
        # or an unlisted addon reviewer.
        if not (addon.has_listed_versions() or
                owner_or_unlisted_reviewer(request, addon)):
            raise http.Http404
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
