import jinja2

from django_jinja import library
from django.template.loader import get_template
from django.utils.translation import ugettext

from olympia import amo
from olympia.access import acl
from olympia.reviews.models import ReviewFlag

from .. import forms


@library.filter
def stars(num, large=False):
    # check for 0.0 incase None was cast to a float. Should
    # be safe since lowest rating you can give is 1.0
    if num is None or num == 0.0:
        return ugettext('Not yet rated')
    else:
        num = min(5, int(round(num)))
        t = get_template('reviews/impala/reviews_rating.html')
        # These are getting renamed for contextual sense in the template.
        return jinja2.Markup(t.render({'rating': num, 'detailpage': large}))


@library.global_function
def reviews_link(addon, collection_uuid=None, link_to_list=False):
    t = get_template('reviews/reviews_link.html')
    return jinja2.Markup(t.render({'addon': addon,
                                   'link_to_list': link_to_list,
                                   'collection_uuid': collection_uuid}))


@library.global_function
def impala_reviews_link(addon, collection_uuid=None, link_to_list=False):
    t = get_template('reviews/impala/reviews_link.html')
    return jinja2.Markup(t.render({'addon': addon,
                                   'link_to_list': link_to_list,
                                   'collection_uuid': collection_uuid}))


@library.global_function
@library.render_with('reviews/report_review.html')
def report_review_popup():
    return {'ReviewFlag': ReviewFlag, 'flag_form': forms.ReviewFlagForm()}


@library.global_function
@library.render_with('reviews/edit_review.html')
def edit_review_form():
    return {'form': forms.ReviewForm()}


@library.global_function
@library.render_with('reviews/edit_review.html')
def edit_review_reply_form():
    return {'form': forms.ReviewReplyForm()}


def user_can_delete_review(request, review):
    """Return whether or not the request.user can delete reviews.

    People who can delete reviews:
      * The original review author.
      * Editors, but only if they aren't listed as an author of the add-on
        and the add-on is flagged for moderation
      * Users in a group with "Users:Edit" privileges.
      * Users in a group with "Addons:Edit" privileges.

    Persona editors can't delete addons reviews.

    """
    is_author = review.addon.has_author(request.user)
    return (
        review.user_id == request.user.id or
        not is_author and (
            (acl.is_editor(request, review.addon) and review.editorreview) or
            acl.action_allowed(request, amo.permissions.USERS_EDIT) or
            acl.action_allowed(request, amo.permissions.ADDONS_EDIT)))


@library.global_function
@jinja2.contextfunction
def check_review_delete(context, review):
    return user_can_delete_review(context['request'], review)
