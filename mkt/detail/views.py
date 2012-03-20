import jingo

from django import http

from access import acl
from addons.models import Addon
from addons.decorators import addon_view_factory
from amo.decorators import json_view, login_required, post_required, write
from mkt.webapps.models import Installed

addon_view = addon_view_factory(qs=Addon.objects.valid)
addon_enabled_view = addon_view_factory(qs=Addon.objects.enabled)


@addon_view
def detail(request, addon):
    """Product details page."""
    return jingo.render(request, 'detail/app.html', {'product': addon})


@addon_enabled_view
def privacy(request, addon):
    if not (addon.is_public() or acl.check_reviewer(request)):
        raise http.Http404
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())
    return jingo.render(request, 'detail/privacy.html', {'product': addon})


@json_view
@addon_view
@login_required
@post_required
@write
def record(request, addon):
    if addon.is_webapp():
        installed, c = Installed.objects.safer_get_or_create(addon=addon,
            user=request.amo_user)
        return {'addon': addon.pk,
                'receipt': installed.receipt if installed else ''}
