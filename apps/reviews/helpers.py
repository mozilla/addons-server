import math

import jinja2

import jingo
from tower import ugettext as _


@jingo.register.filter
def stars(num):
    if num is None:
        return _('Not yet rated')
    else:
        num = int(math.ceil(num))
        rating = '<span itemprop="rating">%s</span>' % num
        title = _('Rated %s out of 5 stars') % num
        msg = _('Rated %s out of 5 stars') % rating
        s = (u'<span class="stars stars-{num}" title="{title}">{msg}</span>'
             .format(num=num, title=title, msg=msg))
        return jinja2.Markup(s)


@jingo.register.filter
def reviews_link(addon, collection_uuid=None):
    t = jingo.env.get_template('reviews/reviews_link.html')
    return jinja2.Markup(t.render(addon=addon,
                                  collection_uuid=collection_uuid))
