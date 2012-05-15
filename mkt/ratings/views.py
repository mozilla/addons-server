from django import http
from django.shortcuts import get_object_or_404

import commonware.log

from addons.decorators import addon_view_factory, has_purchased
from addons.models import Addon
from amo.decorators import json_view, login_required, post_required
from reviews.models import Review
from reviews.helpers import user_can_delete_review


log = commonware.log.getLogger('mkt.ratings')
addon_view = addon_view_factory(qs=Addon.objects.valid)


@addon_view
def review_list(request, addon, review_id=None, user_id=None):
    return http.HttpResponse()


@addon_view
@post_required
@login_required(redirect=False)
@json_view
def flag(request, addon, review_id):
    return http.HttpResponse()


@addon_view
@post_required
@login_required(redirect=False)
def delete(request, addon, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    if not user_can_delete_review(request, review):
        return http.HttpResponseForbidden()
    return http.HttpResponse()


@addon_view
@json_view
@login_required(redirect=False)
@post_required
def edit(request, addon, review_id):
    return http.HttpResponse()


@addon_view
@login_required
@has_purchased
def add(request, addon):
    return http.HttpResponse()
