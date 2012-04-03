from jingo import register
import jinja2
from tower import ugettext as _, ugettext_lazy as _lazy, ungettext as ngettext

import amo
from amo.helpers import breadcrumbs
from amo.urlresolvers import reverse

from mkt.developers.helpers import mkt_page_title
from .views import queue_counts


@register.function
@jinja2.contextfunction
def reviewers_breadcrumbs(context, queue=None, addon_queue=None, items=None):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Editor Tools'
    breadcrumbs.

    **items**
        list of [(url, label)] to be inserted after Add-on.
    **addon_queue**
        Addon object. This sets the queue by addon type or addon status.
    **queue**
        Explicit queue type to set.
    """
    crumbs = [(reverse('reviewers.home'), _('Reviewer Tools'))]

    if addon_queue and addon_queue.type == amo.ADDON_WEBAPP:
        queue = 'apps'

    if queue:
        queues = {'apps': _('Apps')}

        if items and not queue == 'queue':
            url = reverse('reviewers.queue_%s' % queue)
        else:
            # The Addon is the end of the trail.
            url = None
        crumbs.append((url, queues[queue]))

    if items:
        crumbs.extend(items)
    return breadcrumbs(context, crumbs, add_default=False)


@register.function
@jinja2.contextfunction
def reviewers_page_title(context, title=None, addon=None):
    if addon:
        title = u'%s | %s' % (title, addon.name)
    else:
        section = _lazy('Reviewer Tools')
        title = u'%s | %s' % (title, section) if title else section
    return mkt_page_title(context, title)


@register.function
@jinja2.contextfunction
def queue_tabnav(context):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    counts = queue_counts()
    tabnav = [('apps', 'queue_apps',
               (ngettext('Apps ({0})', 'Apps ({0})', counts['apps'])
                .format(counts['apps'])))]
    return tabnav
