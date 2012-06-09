from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _

from access import acl
import amo
import amo.log
from addons.decorators import addon_view_factory, has_purchased
from addons.models import Addon
from amo.decorators import json_view, login_required, post_required
from amo.helpers import absolutify
from reviews.models import Review
from reviews.helpers import user_can_delete_review
from reviews.views import get_flags

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
def review_list(request, addon, review_id=None, user_id=None, rating=None):
    qs = Rating.objects.valid().filter(addon=addon).order_by('-created')

    ctx = {'product': addon, 'score': rating, 'review_perms': {}}

    # If we want to filter by only positive or only negative.
    score = {'positive': 1, 'negative': -1}.get(rating)
    if score:
        qs = qs.filter(score=score)

    if review_id is not None:
        qs = qs.filter(pk=review_id)
        ctx['page'] = 'detail'
        # If this is a dev reply, find the first msg for context.
        review = get_object_or_404(Rating, pk=review_id)
        if review.reply_to_id:
            review_id = review.reply_to_id
            ctx['reply'] = review
    elif user_id is not None:
        qs = qs.filter(user=user_id)
        ctx['page'] = 'user'
        if not qs:
            raise http.Http404()
    else:
        ctx['page'] = 'list'
        qs = qs.filter(is_latest=True)

    ctx['ratings'] = ratings = amo.utils.paginate(request, qs)
    ctx['replies'] = Rating.get_replies(ratings.object_list)
    ctx['review_history'] = [[2, 12], [50, 2], [3, 0], [4, 1]]
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': acl.action_allowed(request, 'Addons', 'Edit'),
            'is_editor': acl.check_reviewer(request),
            'is_author': acl.check_addon_ownership(request, addon, viewer=True,
                                                   dev=True, support=True),
        }
        ctx['flags'] = get_flags(request, ratings.object_list)
    return jingo.render(request, 'ratings/listing.html', ctx)


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
        review = Review.objects.create(**_review_details(request, addon, form))
        amo.log(amo.LOG.ADD_REVIEW, addon, review)
        log.debug('New review: %s' % review.id)
        messages.success(request, _('Your review was successfully added!'))

        reply_url = addon.get_ratings_url('reply', args=[addon, review.id],
                                          add_prefix=False)
        data = {'name': addon.name,
                'rating': '%s out of 5 stars' % details['rating'],
                'review': details['body'],
                'reply_url': absolutify(reply_url)}

        # emails = addon.values_list('email', flat=True)
        # send_mail('reviews/emails/add_review.ltxt',
        #           u'Mozilla Marketplace User Review: %s' % addon.name,
        #           emails, Context(data), 'new_review')

        return redirect(addon.get_ratings_url('list'))

    return jingo.render(request, 'ratings/add.html',
                        {'product': addon, 'form': form})
