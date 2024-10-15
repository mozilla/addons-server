import functools

from django import http
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.translation import gettext

import waffle
from rest_framework import status
from rest_framework.response import Response

from olympia.access import acl
from olympia.addons.models import Addon


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
            except Addon.DoesNotExist as exc:
                raise http.Http404 from exc
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
        if not (
            has_listed_versions
            or acl.author_or_unlisted_viewer_or_reviewer(request.user, addon)
        ):
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


def require_submissions_enabled(f):
    """Require the enable-submissions waffle flag to be enabled."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        flag = waffle.get_waffle_flag_model().get('enable-submissions')
        if flag.is_active(request):
            return f(request, *args, **kw)
        reason = flag.note if hasattr(flag, 'note') else None
        if getattr(request, 'is_api', True):
            return Response(
                {
                    'error': gettext('Add-on uploads are temporarily unavailable.'),
                    'reason': reason,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return TemplateResponse(
            request,
            'amo/submissions_disabled.html',
            status=503,
            context={'reason': reason},
        )

    return wrapper
