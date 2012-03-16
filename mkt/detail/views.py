import jingo

from addons.models import Addon
from addons.decorators import addon_view_factory
from amo.decorators import json_view, login_required, post_required, write
from mkt.webapps.models import Installed


addon_view = addon_view_factory(qs=Addon.objects.valid)


@addon_view
def detail(request, addon):
    """Product details page."""

    ctx = {
        'product': addon,
    }

    return jingo.render(request, 'detail/app.html', ctx)


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
