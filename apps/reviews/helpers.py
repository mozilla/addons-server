import math

import jinja2

import jingo
from l10n import ugettext as _


@jingo.register.filter
def stars(num):
    if num is None:
        return _('Not yet rated')
    else:
        stars = int(math.ceil(num))
        msg = _('Rated %s out of 5 stars') % stars
        s = (u'<span class="stars stars-{num}" title="{msg}">{msg}</span>'
             .format(num=stars, msg=msg))
        return jinja2.Markup(s)


@jingo.register.filter
def reviews_link(addon, collection_uuid=None):
    t = jingo.env.get_template('reviews/reviews_link.html')
    return jinja2.Markup(t.render(addon=addon,
                                  collection_uuid=collection_uuid))
