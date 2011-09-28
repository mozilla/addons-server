import jinja2

import jingo
from tower import ugettext as _


@jingo.register.filter
def stars(num, large=False):
    # check for 0.0 incase None was cast to a float. Should
    # be safe since lowest rating you can give is 1.0
    if num is None or num == 0.0:
        return _('Not yet rated')
    else:
        num = min(5, int(round(num)))
        rating = '<span itemprop="rating">%s</span>' % num
        title = _('Rated %s out of 5 stars') % num
        msg = _('Rated %s out of 5 stars') % rating
        size = 'large ' if large else ''
        s = (u'<span class="stars {size}stars-{num}" title="{title}">{msg}</span>'
             .format(num=num, size=size, title=title, msg=msg))
        return jinja2.Markup(s)  # Inspected by #10


@jingo.register.function
def reviews_link(addon, collection_uuid=None, link_to_list=False):
    t = jingo.env.get_template('reviews/reviews_link.html')
    return jinja2.Markup(t.render(addon=addon, link_to_list=link_to_list,
                                  collection_uuid=collection_uuid))


@jingo.register.function
def impala_reviews_link(addon, collection_uuid=None):
    t = jingo.env.get_template('reviews/impala/reviews_link.html')
    return jinja2.Markup(t.render(addon=addon,
                                  collection_uuid=collection_uuid))


@jingo.register.inclusion_tag('reviews/mobile/reviews_link.html')
@jinja2.contextfunction
def mobile_reviews_link(context, addon):
    c = dict(context.items())
    c.update(addon=addon)
    return c


@jingo.register.inclusion_tag('reviews/report_review.html')
@jinja2.contextfunction
def report_review_popup(context):
    return context
