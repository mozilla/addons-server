from django.template.loader import get_template
from django.utils.translation import ugettext

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.ratings.models import RatingFlag

from .. import forms


@library.filter
def stars(num, large=False):
    # check for 0.0 incase None was cast to a float. Should
    # be safe since lowest rating you can give is 1.0
    if num is None or num == 0.0:
        return ugettext('Not yet rated')
    else:
        num = min(5, int(round(num)))
        t = get_template('ratings/impala/reviews_rating.html')
        # These are getting renamed for contextual sense in the template.
        return jinja2.Markup(t.render({'rating': num, 'detailpage': large}))


@library.global_function
def reviews_link(addon, collection_uuid=None):
    t = get_template('ratings/reviews_link.html')
    return jinja2.Markup(
        t.render({'addon': addon, 'collection_uuid': collection_uuid})
    )


@library.global_function
def impala_reviews_link(addon, collection_uuid=None):
    t = get_template('ratings/impala/reviews_link.html')
    return jinja2.Markup(
        t.render({'addon': addon, 'collection_uuid': collection_uuid})
    )


@library.global_function
@library.render_with('ratings/report_review.html')
def report_review_popup():
    return {'RatingFlag': RatingFlag, 'flag_form': forms.RatingFlagForm()}


@library.global_function
@library.render_with('ratings/edit_review.html')
def edit_review_form():
    return {'form': forms.RatingForm()}


@library.global_function
@library.render_with('ratings/edit_review.html')
def edit_review_reply_form():
    return {'form': forms.RatingReplyForm()}


def user_can_delete_review(request, review):
    """Return whether or not the request.user can delete reviews.

    People who can delete reviews:
      * The original review author.
      * Reviewers with Ratings:Moderate, if the review has been flagged and
        they are not an author of this add-on.
      * Users in a group with "Users:Edit" or "Addons:Edit" privileges and
        they are not an author of this add-on.
    """
    is_rating_author = review.user_id == request.user.id
    is_addon_author = review.addon.has_author(request.user)
    is_moderator = (
        acl.action_allowed(request, amo.permissions.RATINGS_MODERATE)
        and review.editorreview
    )
    can_edit_users_or_addons = acl.action_allowed(
        request, amo.permissions.USERS_EDIT
    ) or acl.action_allowed(request, amo.permissions.ADDONS_EDIT)

    return is_rating_author or (
        not is_addon_author and (is_moderator or can_edit_users_or_addons)
    )


@library.global_function
@jinja2.contextfunction
def check_review_delete(context, review):
    return user_can_delete_review(context['request'], review)
