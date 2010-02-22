import math
import urllib
import urlparse

from django.core.urlresolvers import reverse
from l10n import ugettext as _, ungettext

import jinja2

from jingo import register


@register.filter
def stars(num):
    if num is None:
        return _('Not yet rated')
    else:
        stars = int(math.ceil(num))
        msg = _('Rated %s out of 5 stars') % stars
        s = ('<span class="stars stars-{num}" title="{msg}">{msg}</span>'
             .format(num=stars, msg=msg))
        return jinja2.Markup(s)


@register.filter
def reviews_link(addon, collection_uuid=None):
    try:
        rating = float(addon.average_rating)
    except ValueError:
        rating = None
    stars_ = stars(rating)

    url = list(urlparse.urlsplit(reverse('addons.detail', args=[addon.id])))
    if collection_uuid:
        url[3] = urllib.urlencode({'collection_uuid': collection_uuid})
    url[4] = 'reviews'

    msg = (ungettext('{num} review', '{num} reviews', addon.total_reviews)
           .format(num=addon.total_reviews))
    s = ('{stars} <a href="{url}"><strong>{msg}</strong></a>'
         .format(stars=unicode(stars_), url=urlparse.urlunsplit(url), msg=msg))
    return jinja2.Markup(s)
