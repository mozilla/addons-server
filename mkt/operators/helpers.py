import jinja2
from jingo import register

from tower import ugettext as _, ugettext_lazy as _lazy

from mkt.developers.helpers import mkt_page_title


@register.function
@jinja2.contextfunction
def operators_page_title(context, title=None):
    section = _lazy('Operator Dashboard')
    title = u'%s | %s' % (title, section) if title else section
    return mkt_page_title(context, title)
