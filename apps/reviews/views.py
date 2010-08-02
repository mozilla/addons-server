from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _

import amo.utils
from amo.decorators import post_required, json_view, login_required
from access import acl
from addons.models import Addon

from .models import Review, ReviewFlag, GroupedRating
from . import forms

log = commonware.log.getLogger('z.reviews')


def flag_context():
    return dict(ReviewFlag=ReviewFlag,
                flag_form=forms.ReviewFlagForm())


def review_list(request, addon_id, review_id=None, user_id=None):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    q = (Review.objects.valid().filter(addon=addon)
         .order_by('-created'))

    ctx = {'addon': addon,
           'grouped_ratings': GroupedRating.get(addon_id)}
    ctx.update(flag_context())

    if review_id is not None:
        ctx['page'] = 'detail'
        # If this is a dev reply, find the first msg for context.
        review = get_object_or_404(Review.objects.all(), pk=review_id)
        if review.reply_to_id:
            review_id = review.reply_to_id
            ctx['reply'] = review
        q = q.filter(pk=review_id)
    elif user_id is not None:
        ctx['page'] = 'user'
        q = q.filter(user=user_id)
    else:
        ctx['page'] = 'list'
        q = q.filter(is_latest=True)

    ctx['reviews'] = reviews = amo.utils.paginate(request, q)
    if not reviews.object_list:
        raise http.Http404()

    ctx['replies'] = get_replies(reviews.object_list)
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': acl.action_allowed(request, 'Admin', 'EditAnyAddon'),
            'is_editor': acl.action_allowed(request, 'Editor', '%'),
            'is_author': acl.check_ownership(request, addon,
                                             require_owner=True),
            'can_delete': acl.action_allowed(request, 'Editors',
                                             'DeleteReview'),
        }
        ctx['flags'] = get_flags(request, reviews.object_list)
    else:
        ctx['review_perms'] = {}
    return jingo.render(request, 'reviews/review_list.html', ctx)


def get_replies(reviews):
    reviews = [r.id for r in reviews]
    qs = Review.objects.filter(reply_to__in=reviews)
    return dict((r.reply_to_id, r) for r in qs)


def get_flags(request, reviews):
    reviews = [r.id for r in reviews]
    qs = ReviewFlag.objects.filter(review__in=reviews, user=request.user.id)
    return dict((r.review_id, r) for r in qs)


@post_required
@login_required(redirect=False)
@json_view
def flag(request, addon_id, review_id):
    d = dict(review=review_id, user=request.user.id)
    try:
        instance = ReviewFlag.objects.get(**d)
    except ReviewFlag.DoesNotExist:
        instance = None
    data = dict(request.POST.items(), **d)
    form = forms.ReviewFlagForm(data, instance=instance)
    if form.is_valid():
        form.save()
        Review.objects.filter(id=review_id).update(editorreview=True)
        return {'msg': _('Thanks; this review has been flagged '
                         'for editor approval.')}
    else:
        return json_view.error(unicode(form.errors))


@post_required
@login_required(redirect=False)
def delete(request, addon_id, review_id):
    if not acl.action_allowed(request, 'Editors', 'DeleteReview'):
        return http.HttpResponseForbidden()
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon_id)
    review.delete()
    log.info('DELETE: %s deleted %s by %s ("%s": "%s")' %
             (request.amo_user.display_name, review_id,
              review.user.display_name, review.title, review.body))
    return http.HttpResponse()


def _review_details(request, addon, form):
    d = dict(addon_id=addon.id, user_id=request.user.id,
             version_id=addon.current_version.id,
             ip_address=request.META.get('REMOTE_ADDR', ''))
    d.update(**form.cleaned_data)
    return d


@login_required
def reply(request, addon_id, review_id):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    is_admin = acl.action_allowed(request, 'Admin', 'EditAnyAddon')
    is_author = acl.check_ownership(request, addon, require_owner=True)
    if not (is_admin or is_author):
        return http.HttpResponseForbidden()

    review = get_object_or_404(Review.objects, pk=review_id, addon=addon_id)
    form = forms.ReviewReplyForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            d = dict(reply_to=review, addon=addon,
                     defaults=dict(user=request.amo_user))
            reply, new = Review.objects.get_or_create(**d)
            for key, val in _review_details(request, addon, form).items():
                setattr(reply, key, val)
            reply.save()
            action = 'New' if new else 'Edited'
            log.debug('%s reply to %s: %s' % (action, review_id, reply.id))
            return redirect('reviews.detail', addon_id, review_id)
    ctx = dict(review=review, form=form, addon=addon)
    ctx.update(flag_context())
    return jingo.render(request, 'reviews/reply.html', ctx)


@login_required
def add(request, addon_id):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    form = forms.ReviewForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            details = _review_details(request, addon, form)
            review = Review.objects.create(**details)
            log.debug('New review: %s' % review.id)
            return redirect('reviews.detail', addon_id, review.id)
    return jingo.render(request, 'reviews/add.html',
                        dict(addon=addon, form=form))


@login_required(redirect=False)
@post_required
def edit(request, addon_id, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon_id)
    is_admin = acl.action_allowed(request, 'Admin', 'EditAnyAddon')
    if not (request.user.id == review.user.id or is_admin):
        return http.HttpResponseForbidden()
    cls = forms.ReviewReplyForm if review.reply_to else forms.ReviewForm
    form = cls(request.POST)
    if form.is_valid():
        for field in form.fields:
            if field in form.cleaned_data:
                setattr(review, field, form.cleaned_data[field])
        review.save()
        return http.HttpResponse()
    else:
        return json_view.error(form.errors)
