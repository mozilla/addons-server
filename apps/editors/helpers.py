import jinja2
from jingo import register
from tower import ugettext as _

from amo.helpers import page_title


@register.function
@jinja2.contextfunction
def editor_page_title(context, title=None, addon=None):
    """Wrapper for editor page titles.  Eerily similar to dev_page_title."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        devhub = _('Editor Tools')
        title = '%s :: %s' % (title, devhub) if title else devhub
    return page_title(context, title)
