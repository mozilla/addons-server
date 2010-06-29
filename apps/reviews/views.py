from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404

import jingo
from tower import ugettext as _

import amo.utils
from amo.decorators import post_required, json_view
from access import acl
from addons.models import Addon

from .models import Review, ReviewFlag
from .forms import ReviewFlagForm


def review_list(request, addon_id, review_id=None, user_id=None):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    q = (Review.objects.valid().filter(addon=addon)
         .order_by('-created'))

    ctx = {'addon': addon, 'ReviewFlag': ReviewFlag,
           'flag_form': ReviewFlagForm()}

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
    ctx['replies'] = get_replies(reviews.object_list)
    if request.user.is_authenticated():
        ctx['perms'] = {
            'is_admin': acl.action_allowed(request, 'Admin', 'EditAnyAddon'),
            'is_editor': acl.action_allowed(request, 'Editor', '%'),
            'is_author': acl.check_ownership(request, addon,
                                             require_owner=True),
            'can_delete': acl.action_allowed(request, 'Editors',
                                             'DeleteReview'),
        }
        ctx['flags'] = get_flags(request, reviews.object_list)
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
@login_required  # TODO: return a 401?
@json_view
def flag(request, addon_id, review_id):
    d = dict(review=review_id, user=request.user.id)
    try:
        instance = ReviewFlag.objects.get(**d)
    except ReviewFlag.DoesNotExist:
        instance = None
    data = dict(request.POST.items(), **d)
    form = ReviewFlagForm(data, instance=instance)
    if form.is_valid():
        form.save()
        Review.objects.filter(id=review_id).update(editorreview=True)
        return {'msg': _('Thanks; this review has been flagged '
                         'for editor approval.')}
    else:
        return json_view.error(unicode(form.errors))
