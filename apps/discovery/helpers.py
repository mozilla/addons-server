import jinja2
from jingo import register
from tower import ugettext as _

import amo
from access import acl


register.function(acl.has_perm)


@register.inclusion_tag('discovery/addons/pane_link.html')
@jinja2.contextfunction
def disco_pane_link(context, src):
    """
    Details/EULA pages: Link back to the main Discovery Pane add-ons page.
    """
    pos = 0
    if src == 'discovery-pane-details':
        pos = -1
    elif src == 'discovery-pane-eula':
        pos = -2
    c = dict(context.items())
    c.update({'pos': pos})
    return c
