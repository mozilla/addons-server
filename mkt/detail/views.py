import jingo

from addons.models import Addon
from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_purchased, has_not_purchased)
from amo.decorators import json_view, login_required, post_required, write
from reviews.forms import ReviewForm
from reviews.models import Review
from mkt.webapps.models import Installed


addon_view = addon_view_factory(qs=Addon.objects.valid)


@addon_view
def detail(request, addon):
    """Product details page."""

    ctx = {
        'addon': addon,
        'review_form': ReviewForm(),
        'reviews': Review.objects.latest().filter(addon=addon),
    }

    return jingo.render(request, 'mkt/detail.html', ctx)


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
