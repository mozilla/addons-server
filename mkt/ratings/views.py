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
from amo.helpers import absolutify
from amo.decorators import (json_view, login_required, post_required,
                            restricted_content)

from reviews.forms import ReviewReplyForm
from reviews.models import Review
from reviews.helpers import user_can_delete_review
from reviews.tasks import addon_review_aggregates
from reviews.views import get_flags

from mkt.site import messages
from mkt.ratings.forms import ReviewForm


log = commonware.log.getLogger('mkt.ratings')
addon_view = addon_view_factory(qs=Addon.objects.valid)


def _review_details(request, addon, form):
    d = dict(addon_id=addon.id, user_id=request.user.id,
             ip_address=request.META.get('REMOTE_ADDR', ''))
    d.update(**form.cleaned_data)
    return d


@addon_view
def review_list(request, addon, review_id=None, user_id=None, rating=None):
    qs = Review.objects.valid().filter(addon=addon).order_by('-created')

    ctx = {'product': addon, 'score': rating, 'review_perms': {}}

    if review_id is not None:
        qs = qs.filter(pk=review_id)
        ctx['page'] = 'detail'
        # If this is a dev reply, find the first msg for context.
        review = get_object_or_404(Review, pk=review_id)
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

    ctx['ratings'] = ratings = amo.utils.paginate(request, qs, 20)
    ctx['replies'] = Review.get_replies(ratings.object_list)
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': acl.action_allowed(request, 'Addons', 'Edit'),
            'is_editor': acl.check_reviewer(request),
            'is_author': acl.check_addon_ownership(request, addon, viewer=True,
                                                   dev=True, support=True),
        }
        ctx['flags'] = get_flags(request, ratings.object_list)
        ctx['has_review'] = addon.reviews.filter(user=request.user.id).exists()
    return jingo.render(request, 'ratings/listing.html', ctx)


@addon_view
@json_view
@login_required(redirect=False)
@post_required
def edit(request, addon, review_id):
    return http.HttpResponse()


@addon_view
@login_required
@post_required
def reply(request, addon, review_id):
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')
    is_author = acl.check_addon_ownership(request, addon, dev=True)
    if not (is_admin or is_author):
        return http.HttpResponseForbidden()

    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    form = ReviewReplyForm(request.POST or None)
    if form.is_valid():
        d = dict(reply_to=review, addon=addon,
                 defaults=dict(user=request.amo_user))
        reply, new = Review.objects.get_or_create(**d)
        for k, v in _review_details(request, addon, form).items():
            setattr(reply, k, v)
        reply.save()
        action = 'New' if new else 'Edited'
        log.debug('%s reply to %s: %s' % (action, review_id, reply.id))
        messages.success(request, _('Your reply was successfully added!'))

    return http.HttpResponse()


@addon_view
@login_required
@restricted_content
@has_purchased
def add(request, addon):
    if addon.has_author(request.user):
        # Don't let app owners review their own apps.
        return http.HttpResponseForbidden()

    data = request.POST or None

    # Try to get an existing review of the app by this user if we can.
    try:
        existing_review = Review.objects.get(addon=addon, user=request.user)
    except Review.DoesNotExist, Review.MultipleObjectsReturned:
        # If one doesn't exist, set it to None.
        existing_review = None

    # If the user is posting back, try to process the submission.
    if data:
        form = ReviewForm(data)
        if form.is_valid():
            if existing_review:
                cleaned = form.cleaned_data
                # If there's a review to overwrite, overwrite it.
                if (cleaned['body'] != existing_review.body or
                    cleaned['rating'] != existing_review.rating):
                    existing_review.body = cleaned['body']
                    existing_review.rating = cleaned['rating']
                    ip = request.META.get('REMOTE_ADDR', '')
                    existing_review.ip_address = ip

                    existing_review.save()
                    # Update ratings and review counts.
                    addon_review_aggregates.delay(addon.id,
                                                  using='default')

                amo.log(amo.LOG.EDIT_REVIEW, addon, existing_review)
                log.debug('[Review:%s] Edited by %s' % (existing_review.id,
                                                        request.user.id))
                messages.success(request,
                                 _('Your review was updated successfully!'))
            else:
                # If there isn't a review to overwrite, create a new review.
                review = Review.objects.create(
                        **_review_details(request, addon, form))
                amo.log(amo.LOG.ADD_REVIEW, addon, review)
                log.debug('[Review:%s] Created by user %s ' % (review.id,
                                                               request.user.id))
                messages.success(request,
                                 _('Your review was successfully added!'))

            Addon.objects.invalidate(*[addon])
            return redirect(addon.get_ratings_url('list'))

        # If the form isn't valid, we've set `form` so that it can be used when
        # the template is rendered below.

    elif existing_review:
        # If the user isn't posting back but has an existing review, populate
        # the form with their existing review and rating.
        form = ReviewForm({'rating': existing_review.rating,
                           'body': existing_review.body})
    else:
        # If the user isn't posting back and doesn't have an existing review,
        # just show a blank version of the form.
        form = ReviewForm()

    return jingo.render(request, 'ratings/add.html',
                        {'product': addon, 'form': form})
