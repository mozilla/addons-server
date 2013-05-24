import datetime
import urlparse

from django.utils.encoding import smart_str
from django.core.exceptions import ObjectDoesNotExist

import jinja2
import waffle
from jingo import register
from tower import ugettext as _, ugettext_lazy as _lazy


from access import acl
from amo.helpers import impala_breadcrumbs
from amo.urlresolvers import reverse

from mkt.developers.helpers import mkt_page_title
from mkt.reviewers.utils import (AppsReviewing, clean_sort_param,
                                 create_sort_link)


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
                  'reviewing': _('Reviewing'),
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

    Each tuple contains three elements: (named_url. tab_code, tab_text)
    """
    counts = context['queue_counts']
    apps_reviewing = AppsReviewing(context['request']).get_apps()

    # Apps.
    if acl.action_allowed(context['request'], 'Apps', 'Review'):
        rv = [
            ('reviewers.apps.queue_pending', 'pending',
             _('Apps ({0})', counts['pending']).format(counts['pending'])),

            ('reviewers.apps.queue_rereview', 'rereview',
             _('Re-reviews ({0})', counts['rereview']).format(
             counts['rereview'])),

            ('reviewers.apps.queue_updates', 'updates',
             _('Updates ({0})', counts['updates']).format(counts['updates'])),
        ]
        if acl.action_allowed(context['request'], 'Apps', 'ReviewEscalated'):
            rv.append(('reviewers.apps.queue_escalated', 'escalated',
                       _('Escalations ({0})', counts['escalated']).format(
                       counts['escalated'])))
        rv.extend([
            ('reviewers.apps.queue_moderated', 'moderated',
             _('Moderated Reviews ({0})', counts['moderated'])
             .format(counts['moderated'])),

            ('reviewers.apps.apps_reviewing', 'reviewing',
             _('Reviewing ({0})').format(len(apps_reviewing))),
        ])
    else:
        rv = []

    # Themes.
    if (acl.action_allowed(context['request'], 'Personas', 'Review') and
        waffle.switch_is_active('mkt-themes')):
        rv.append(('reviewers.themes.list', 'themes',
                  _('Themes ({0})').format(counts['themes']),))
    return rv


@register.function
@jinja2.contextfunction
def logs_tabnav(context):
    """
    Returns tuple of tab navigation for the log pages.

    Each tuple contains three elements: (named url, tab_code, tab_text)
    """
    rv = []
    # Apps.
    if acl.action_allowed(context['request'], 'Apps', 'Review'):
        rv.append(('reviewers.apps.logs', 'apps', _('Apps')))

    # Themes.
    if (acl.action_allowed(context['request'], 'Personas', 'Review') and
        waffle.switch_is_active('mkt-themes')):
        rv.append(('reviewers.themes.logs', 'themes', _('Themes')))
    return rv


@register.function
@jinja2.contextfunction
def queue_tabnav_themes(context):
    """Similar to queue_tabnav, but for themes."""
    tabs = []
    if acl.action_allowed(context['request'], 'Personas', 'Review'):
        tabs.append((
            'reviewers.themes.queue_themes', 'pending', _('Pending'),
        ))
    if acl.action_allowed(context['request'], 'SeniorPersonasTools', 'View'):
        tabs.append((
            'reviewers.themes.queue_flagged', 'flagged', _('Flagged'),
        ))
        tabs.append((
            'reviewers.themes.queue_rereview', 'rereview', _('Re-review'),
        ))
    return tabs


@register.function
@jinja2.contextfunction
def sort_link(context, pretty_name, sort_field):
    """Get table header sort links.

    pretty_name -- name displayed on table header
    sort_field -- name of get parameter, referenced to in views
    """
    request = context['request']
    sort, order = clean_sort_param(request)

    # Copy search/filter GET parameters.
    get_params = [(k, v) for k, v in
                  urlparse.parse_qsl(smart_str(request.META['QUERY_STRING']))
                  if k not in ('sort', 'order')]

    return create_sort_link(pretty_name, sort_field, get_params,
                            sort, order)


@register.function
@jinja2.contextfunction
def hasOneToOne(context, obj, attr):
    try:
        getattr(obj, attr)
        return True
    except ObjectDoesNotExist:
        return False


@register.function
@jinja2.contextfunction
def is_expired_lock(context, lock):
    return lock.expiry < datetime.datetime.now()
