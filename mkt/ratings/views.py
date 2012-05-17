from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _

import amo
import amo.log
from addons.decorators import addon_view_factory, has_purchased
from addons.models import Addon
from amo.decorators import json_view, login_required, post_required
from reviews.helpers import user_can_delete_review

from mkt.site import messages
from mkt.ratings.models import Rating

from . import forms


log = commonware.log.getLogger('mkt.ratings')
addon_view = addon_view_factory(qs=Addon.objects.valid)


def _review_details(request, addon, form):
    d = dict(addon_id=addon.id, user_id=request.user.id,
             ip_address=request.META.get('REMOTE_ADDR', ''))
    d.update(**form.cleaned_data)
    return d


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
    review = get_object_or_404(Rating.objects, pk=review_id, addon=addon)
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
    if addon.has_author(request.user):
        # Don't let app owners review their own apps.
        return http.HttpResponseForbidden()

    data = request.POST or None
    form = forms.RatingForm(data)
    if data and form.is_valid():
        rating = Rating.objects.create(**_review_details(request, addon, form))
        amo.log(amo.LOG.ADD_REVIEW, addon, rating)
        log.debug('New rating: %s' % rating.id)
        messages.success(request, _('Your review was successfully added!'))
        return redirect(addon.get_detail_url() + '#reviews')
        # TODO: When rating list is done uncomment this (bug 755954).
        #return redirect(addon.get_ratings_url('list'))

    return jingo.render(request, 'ratings/add.html',
                        {'product': addon, 'form': form})
