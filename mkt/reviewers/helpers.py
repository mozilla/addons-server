import jinja2
from jingo import register
from tower import ugettext as _, ugettext_lazy as _lazy

from access import acl
from amo.helpers import impala_breadcrumbs
from amo.urlresolvers import reverse

from mkt.developers.helpers import mkt_page_title


@register.function
@jinja2.contextfunction
def reviewers_breadcrumbs(context, queue=None, items=None):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Editor Tools'
    breadcrumbs.

    **queue**
        Explicit queue type to set.
    **items**
        list of [(url, label)] to be inserted after Add-on.
    """
    crumbs = [(reverse('reviewers.home'), _('Reviewer Tools'))]

    if queue:
        queues = {'pending': _('Apps'),
                  'rereview': _('Re-reviews'),
                  'escalated': _('Escalations'),
                  'moderated': _('Moderated Reviews')}

        if items:
            url = reverse('reviewers.apps.queue_%s' % queue)
        else:
            # The Addon is the end of the trail.
            url = None
        crumbs.append((url, queues[queue]))

    if items:
        crumbs.extend(items)
    return impala_breadcrumbs(context, crumbs, add_default=True)


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
    counts = context['queue_counts']
    rv = [
        ('pending', 'queue_pending',
         _('Apps ({0})', counts['pending']).format(counts['pending'])),
        ('rereview', 'queue_rereview',
         _('Re-reviews ({0})', counts['rereview']).format(counts['rereview'])),
    ]
    if acl.action_allowed(context['request'], 'Apps', 'ReviewEscalated'):
        rv.append(
            ('escalated', 'queue_escalated',
             _('Escalations ({0})',
               counts['escalated']).format(counts['escalated']))
        )
    rv.append(
        ('moderated', 'queue_moderated',
         _('Moderated Reviews ({0})',
           counts['moderated']).format(counts['moderated'])),
    )
    return rv
