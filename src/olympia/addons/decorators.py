import functools

from django import http
from django.shortcuts import get_object_or_404

from olympia.access import acl
from olympia.addons.models import Addon


def owner_or_unlisted_reviewer(request, addon):
    return (
        acl.check_unlisted_addons_reviewer(request)
        # We don't want "admins" here, because it includes anyone with the
        # "Addons:Edit" perm, we only want those with
        # "Addons:ReviewUnlisted" perm (which is checked above).
        or acl.check_addon_ownership(request, addon, admin=False, dev=True)
    )


def addon_view(f, qs=Addon.objects.all, include_deleted_when_checking_versions=False):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        """Provides an addon instance to the view given addon_id, which can be
        an Addon pk, guid or a slug."""
        assert addon_id, 'Must provide addon id, guid or slug'

        lookup_field = Addon.get_lookup_field(addon_id)
        if lookup_field == 'slug':
            addon = get_object_or_404(qs(), slug=addon_id)
        else:
            try:
                if lookup_field == 'pk':
                    addon = qs().get(id=addon_id)
                elif lookup_field == 'guid':
                    addon = qs().get(guid=addon_id)
            except Addon.DoesNotExist:
                raise http.Http404
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.slug and addon.slug != addon_id:
                url = request.path.replace(addon_id, addon.slug, 1)
                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)

        # If the addon has no listed versions it needs either an author
        # (owner/viewer/dev/support) or an unlisted addon reviewer.
        has_listed_versions = addon.has_listed_versions(
            include_deleted=include_deleted_when_checking_versions
        )
        if not (has_listed_versions or owner_or_unlisted_reviewer(request, addon)):
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
