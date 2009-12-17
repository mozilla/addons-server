import math

from django.utils.translation import ugettext as _

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
