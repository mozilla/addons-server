from django.template.loader import get_template
from django.utils.translation import gettext

import markupsafe

from django_jinja import library


@library.filter
def stars(num, large=False):
    # check for 0.0 incase None was cast to a float. Should
    # be safe since lowest rating you can give is 1.0
    if num is None or num == 0.0:
        return gettext('Not yet rated')
    else:
        num = min(5, int(round(num)))
        t = get_template('ratings/reviews_rating.html')
        # These are getting renamed for contextual sense in the template.
        return markupsafe.Markup(t.render({'rating': num, 'detailpage': large}))


@library.global_function
def reviews_link(addon, collection_uuid=None):
    t = get_template('ratings/reviews_link.html')
    return markupsafe.Markup(
        t.render({'addon': addon, 'collection_uuid': collection_uuid})
    )
