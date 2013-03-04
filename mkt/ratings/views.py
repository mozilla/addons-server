from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _

from access import acl
import amo
import amo.log
from amo.urlresolvers import reverse
from addons.decorators import addon_view_factory, has_purchased_or_refunded
from addons.models import Addon
from amo.decorators import (json_view, login_required, post_required,
                            restricted_content)
from lib.metrics import record_action
from mkt.fragments.decorators import bust_fragments_on_post

from reviews.forms import ReviewReplyForm
from reviews.models import Review, ReviewFlag
from reviews.views import get_flags
from stats.models import ClientData, Contribution

from mkt.site import messages
from mkt.ratings.forms import ReviewForm
from mkt.webapps.models import Installed
from mkt.detail.views import detail


log = commonware.log.getLogger('mkt.ratings')
addon_view = addon_view_factory(qs=Addon.objects.valid)


def _review_details(request, addon, form):
    d = dict(addon_id=addon.id, user_id=request.user.id,
             ip_address=request.META.get('REMOTE_ADDR', ''))
    if addon.is_packaged:
        d['version_id'] = addon.current_version.id
    d.update(**form.cleaned_data)
    return d


@addon_view
def review_list(request, addon, review_id=None, user_id=None, rating=None):
    qs = Review.objects.valid().filter(addon=addon).order_by('-created')

    # Mature regions show only reviews from within that region.
    if not request.REGION.adolescent:
        qs = qs.filter(client_data__region=request.REGION.id)
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
    if not ctx.get('reply'):
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


@bust_fragments_on_post('/app/{app_slug}')
@addon_view
@login_required
@post_required
def reply(request, addon, review_id):
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')
    is_author = acl.check_addon_ownership(request, addon, dev=True)
    if not (is_admin or is_author):
        raise PermissionDenied

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
        if new:
            amo.log(amo.LOG.ADD_REVIEW, addon, reply)
        else:
            amo.log(amo.LOG.EDIT_REVIEW, addon, reply)

        log.debug('%s reply to %s: %s' % (action, review_id, reply.id))
        messages.success(request,
                         _('Your reply was successfully added.') if new else
                         _('Your reply was successfully updated.'))

    return redirect(addon.get_ratings_url('list'))


@bust_fragments_on_post('/app/{app_slug}')
@addon_view
@login_required
@restricted_content
@has_purchased_or_refunded
def add(request, addon):
    if addon.has_author(request.user):
        # Don't let app owners review their own apps.
        raise PermissionDenied

    if (request.user.is_authenticated() and
            request.method == 'GET' and (not request.MOBILE or request.TABLET)):
        return detail(request, app_slug=addon.app_slug, add_review=True)

    # Get user agent of user submitting review. If there is an install with
    # logged user agent that matches the current user agent, hook up that
    # install's client data with the rating. If there aren't any install that
    # match, use the most recent install. This implies that user must have an
    # install to submit a review, but not sure if that logic is worked in, so
    # default client_data to None.
    client_data = None
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    install = (Installed.objects.filter(user=request.user, addon=addon)
                                .order_by('-created'))
    install_w_user_agent = (install.filter(client_data__user_agent=user_agent)
                                   .order_by('-created'))
    has_review = False
    try:
        if install_w_user_agent:
            client_data = install_w_user_agent[0].client_data
        elif install:
            client_data = install[0].client_data
    except ClientData.DoesNotExist:
        client_data = None

    data = request.POST or None

    # Try to get an existing review of the app by this user if we can.
    filters = dict(addon=addon, user=request.user)
    if addon.is_packaged:
        filters['version'] = addon.current_version

    try:
        existing_review = Review.objects.valid().filter(**filters)[0]
    except IndexError:
        existing_review = None

    # If the user is posting back, try to process the submission.
    if data:
        form = ReviewForm(data)
        if form.is_valid():
            cleaned = form.cleaned_data
            if existing_review:
                # If there's a review to overwrite, overwrite it.
                if (cleaned['body'] != existing_review.body or
                    cleaned['rating'] != existing_review.rating):
                    existing_review.body = cleaned['body']
                    existing_review.rating = cleaned['rating']
                    ip = request.META.get('REMOTE_ADDR', '')
                    existing_review.ip_address = ip
                    if 'flag' in cleaned and cleaned['flag']:
                        existing_review.flag = True
                        existing_review.editorreview = True
                        rf = ReviewFlag(review=existing_review,
                                        user_id=request.user.id,
                                        flag=ReviewFlag.OTHER, note='URLs')
                        rf.save()
                    existing_review.save()

                amo.log(amo.LOG.EDIT_REVIEW, addon, existing_review)
                log.debug('[Review:%s] Edited by %s' % (existing_review.id,
                                                        request.user.id))
                messages.success(request,
                                 _('Your review was updated successfully!'))

                # If there is a developer reply to the review, delete it. We do
                # this per bug 777059.
                try:
                    reply = existing_review.replies.all()[0]
                except IndexError:
                    pass
                else:
                    log.debug('[Review:%s] Deleted reply to %s' % (
                        reply.id, existing_review.id))
                    reply.delete()

            else:
                # If there isn't a review to overwrite, create a new review.
                review = Review.objects.create(client_data=client_data,
                                               **_review_details(
                                                   request, addon, form))
                if 'flag' in cleaned and cleaned['flag']:
                    rf = ReviewFlag(review=review, user_id=request.user.id,
                                    flag=ReviewFlag.OTHER, note='URLs')
                    rf.save()
                amo.log(amo.LOG.ADD_REVIEW, addon, review)
                log.debug('[Review:%s] Created by user %s ' %
                          (review.id, request.user.id))
                messages.success(request,
                                 _('Your review was successfully added!'))
                record_action('new-review', request, {'app-id': addon.id})

            return redirect(addon.get_ratings_url('list'))

        # If the form isn't valid, we've set `form` so that it can be used when
        # the template is rendered below.

    elif existing_review:
        # If the user isn't posting back but has an existing review, populate
        # the form with their existing review and rating.
        form = ReviewForm({'rating': existing_review.rating or 1,
                           'body': existing_review.body})
        has_review = True
    else:
        # If the user isn't posting back and doesn't have an existing review,
        # just show a blank version of the form.
        form = ReviewForm()

    # Get app's support url, either from support flow if contribution exists or
    # author's support url.
    support_email = str(addon.support_email) if addon.support_email else None
    try:
        contrib_id = (Contribution.objects
                      .filter(user=request.user, addon=addon,
                              type__in=(amo.CONTRIB_PURCHASE,
                                        amo.CONTRIB_INAPP,
                                        amo.CONTRIB_REFUND))
                      .order_by('-created')[0].id)
        support_url = reverse('support', args=[contrib_id])
    except IndexError:
        support_url = addon.support_url

    return jingo.render(request, 'ratings/add.html',
                        {'product': addon, 'form': form,
                         'support_url': support_url,
                         'has_review': has_review,
                         'support_email': support_email,
                         'page_parent': addon.get_detail_url() if
                                        not existing_review else ''})
