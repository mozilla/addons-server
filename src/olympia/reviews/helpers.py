import jinja2

import jingo
from django.utils.translation import ugettext as _

from olympia.access import acl
from olympia.reviews.models import ReviewFlag

from . import forms


@jingo.register.filter
def stars(num, large=False):
    # check for 0.0 incase None was cast to a float. Should
    # be safe since lowest rating you can give is 1.0
    if num is None or num == 0.0:
        return _('Not yet rated')
    else:
        num = min(5, int(round(num)))
        t = jingo.get_env().get_template('reviews/impala/reviews_rating.html')
        # These are getting renamed for contextual sense in the template.
        return jinja2.Markup(t.render({'rating': num, 'detailpage': large}))


@jingo.register.function
def reviews_link(addon, collection_uuid=None, link_to_list=False):
    t = jingo.get_env().get_template('reviews/reviews_link.html')
    return jinja2.Markup(t.render({'addon': addon,
                                   'link_to_list': link_to_list,
                                   'collection_uuid': collection_uuid}))


@jingo.register.function
def impala_reviews_link(addon, collection_uuid=None, link_to_list=False):
    t = jingo.get_env().get_template('reviews/impala/reviews_link.html')
    return jinja2.Markup(t.render({'addon': addon,
                                   'link_to_list': link_to_list,
                                   'collection_uuid': collection_uuid}))


@jingo.register.inclusion_tag('reviews/mobile/reviews_link.html')
@jinja2.contextfunction
def mobile_reviews_link(context, addon):
    c = dict(context.items())
    c.update(addon=addon)
    return c


@jingo.register.inclusion_tag('reviews/report_review.html')
@jinja2.contextfunction
def report_review_popup(context):
    c = dict(context.items())
    c.update(ReviewFlag=ReviewFlag, flag_form=forms.ReviewFlagForm())
    return c


@jingo.register.inclusion_tag('reviews/edit_review.html')
@jinja2.contextfunction
def edit_review_form(context):
    c = dict(context.items())
    c.update(form=forms.ReviewForm())
    return c


@jingo.register.inclusion_tag('reviews/edit_review.html')
@jinja2.contextfunction
def edit_review_reply_form(context):
    c = dict(context.items())
    c.update(form=forms.ReviewReplyForm())
    return c


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
            acl.action_allowed(request, 'Users', 'Edit') or
            acl.action_allowed(request, 'Addons', 'Edit')))


@jingo.register.function
@jinja2.contextfunction
def check_review_delete(context, review):
    return user_can_delete_review(context['request'], review)
