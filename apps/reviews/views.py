from django.shortcuts import get_object_or_404

import jingo

import amo.utils
from addons.models import Addon
from versions.models import Version

from .models import Review


def review_list(request, addon_id):
    addon = get_object_or_404(Addon, id=addon_id)
    q = Review.objects.filter(addon=addon, is_latest=True).order_by('-created')
    reviews = amo.utils.paginate(request, q)
    return jingo.render(request, 'reviews/review_list.html',
                        {'addon': addon, 'reviews': reviews})
