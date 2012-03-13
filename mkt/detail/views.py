import jingo
import jinja2

from addons.models import Addon
from addons.decorators import (addon_view_factory, can_be_purchased,
                               has_purchased, has_not_purchased)

from reviews.forms import ReviewForm
from reviews.models import Review, GroupedRating


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
