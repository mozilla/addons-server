import jinja2
from jingo import register
from tower import ugettext as _, ugettext_lazy as _lazy
import waffle

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
                  'updates': _('Updates'),
                  'escalated': _('Escalations'),
                  'moderated': _('Moderated Reviews'),
                  'themes': _('Themes')}

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
    """
    Returns tuple of tab navigation for the queue pages.

    Each tuple contains four elements: (url namespace prefix, tab_code,
                                        page_url, tab_text)
    """
    counts = context['queue_counts']

    # Apps.
    if acl.action_allowed(context['request'], 'Apps', 'Review'):
        rv = [
            ('apps', 'pending', 'queue_pending',
             _('Apps ({0})', counts['pending']).format(counts['pending'])),
            ('apps', 'rereview', 'queue_rereview',
             _('Re-reviews ({0})', counts['rereview'])
             .format(counts['rereview'])),
            ('apps', 'updates', 'queue_updates',
             _('Updates ({0})', counts['updates']).format(counts['updates'])),
        ]
        if acl.action_allowed(context['request'], 'Apps', 'ReviewEscalated'):
            rv.append(
                ('apps', 'escalated', 'queue_escalated',
                 _('Escalations ({0})',
                   counts['escalated']).format(counts['escalated']))
            )
        rv.append(
            ('apps', 'moderated', 'queue_moderated',
             _('Moderated Reviews ({0})',
               counts['moderated']).format(counts['moderated'])),
        )
    else:
        rv = []

    # Themes.
    if (acl.action_allowed(context['request'], 'Personas', 'Review') and
        waffle.switch_is_active('mkt-themes')):
        rv.append(
            ('themes', 'themes', 'queue_themes',
             _('Themes ({0})',
               counts['themes']).format(counts['themes'])),
        )
    return rv


@register.function
@jinja2.contextfunction
def logs_tabnav(context):
    """
    Returns tuple of tab navigation for the log pages.

    Each tuple contains two elements: (page_url, tab_text)
    """
    rv = []
    # Apps.
    if acl.action_allowed(context['request'], 'Apps', 'Review'):
        rv.append(('reviewers.apps.logs', _('Apps')))

    # Themes.
    if (acl.action_allowed(context['request'], 'Personas', 'Review') and
        waffle.switch_is_active('mkt-themes')):
        rv.append(('reviewers.themes.logs', _('Themes')))
    return rv
