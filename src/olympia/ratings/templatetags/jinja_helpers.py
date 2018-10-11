from django.template.loader import get_template
from django.utils.translation import ugettext

import jinja2

from django_jinja import library


from olympia.ratings.models import RatingFlag
from olympia.ratings.permissions import user_can_delete_rating

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
    return jinja2.Markup(t.render({'addon': addon,
                                   'collection_uuid': collection_uuid}))


@library.global_function
def impala_reviews_link(addon, collection_uuid=None):
    t = get_template('ratings/impala/reviews_link.html')
    return jinja2.Markup(t.render({'addon': addon,
                                   'collection_uuid': collection_uuid}))


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


@library.global_function
@jinja2.contextfunction
def check_review_delete(context, rating):
    return user_can_delete_rating(context['request'], rating)
