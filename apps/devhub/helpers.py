from django.utils import encoding

import jinja2
from jingo import env, register
from tower import ugettext as _

from amo import urlresolvers
from amo.helpers import breadcrumbs, page_title
from addons.helpers import new_context


@register.inclusion_tag('devhub/addons/listing/items.html')
@jinja2.contextfunction
def dev_addon_listing_items(context, addons, src=None, notes={}):
    return new_context(**locals())


@register.function
@jinja2.contextfunction
def dev_page_title(context, title=None):
    """
    Wrapper function for ``page_title``, passing 'Developer Hub' as the root
    page title. If no title is passed, page title defaults to 'Developer Hub'.
    """
    if title:
        title_chunk = '%s :: ' % encoding.smart_unicode(title)
    else:
        title_chunk = ''
    return page_title(context, '%s%s' % (title_chunk, _('Developer Hub')))


@register.function
@jinja2.contextfunction
def dev_breadcrumbs(context, items=list(), add_default=False):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Developer Hub' breadcrumb
    to ``items`` argument, and ``add_default`` argument defaults to False.
    Accepts: [(url, label)]
    """
    crumbs = [(urlresolvers.reverse('devhub.index'), _('Developer Hub'))]
    return breadcrumbs(context, crumbs + items, add_default)
