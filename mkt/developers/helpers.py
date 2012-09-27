from collections import defaultdict
import urllib

from django.conf import settings
from django.utils.encoding import smart_unicode

import chardet
import jinja2
from jingo import register
from jingo.helpers import datetime as jingo_datetime
from tower import ugettext as _, ungettext as ngettext

import amo
from amo.urlresolvers import reverse
from access import acl
from addons.helpers import new_context

from mkt.site.helpers import mkt_breadcrumbs

register.function(acl.check_addon_ownership)


@register.inclusion_tag('developers/apps/listing/items.html')
@jinja2.contextfunction
def hub_addon_listing_items(context, addons, src=None, notes=None):
    return new_context(**locals())


@register.function
@jinja2.contextfunction
def hub_page_title(context, title=None, addon=None):
    """Wrapper for developer page titles."""
    if addon:
        title = u'%s | %s' % (title, addon.name)
    else:
        devhub = _('Developers')
        title = '%s | %s' % (title, devhub) if title else devhub
    return mkt_page_title(context, title)


@register.function
@jinja2.contextfunction
def mkt_page_title(context, title, force_webapps=False):
    title = smart_unicode(title)
    base_title = _('Firefox Marketplace')
    return u'%s | %s' % (title, base_title)


@register.function
@jinja2.contextfunction
def hub_breadcrumbs(context, addon=None, items=None, add_default=False):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Developers' breadcrumb.

    **items**
        list of [(url, label)] to be inserted after Add-on.
    **addon**
        Adds the Add-on name to the end of the trail.  If items are
        specified then the Add-on will be linked.
    **add_default**
        Prepends trail back to home when True.  Default is False.
    **impala**
        Whether to use the impala_breadcrumbs helper. Default is False.
    """
    can_view = getattr(context['request'], 'can_view_consumer', True)
    if can_view:
        crumbs = [(reverse('ecosystem.landing'), _('Developers'))]
    else:
        crumbs = [(reverse('mkt.developers.apps'), _('My Submissions'))]
    if can_view:
        title = _('My Submissions')
        link = reverse('mkt.developers.apps')
    else:
        title = link = None

    if addon:
        if can_view:
            if not addon and not items:
                # We are at the end of the crumb trail.
                crumbs.append((None, title))
            else:
                crumbs.append((link, title))
        if items:
            url = addon.get_dev_url()
        else:
            # The Addon is the end of the trail.
            url = None
        crumbs.append((url, addon.name))
    if items:
        crumbs.extend(items)

    if len(crumbs) == 1:
        crumbs = []

    return mkt_breadcrumbs(context, items=crumbs, add_default=can_view)


@register.inclusion_tag('developers/versions/add_file_modal.html')
@jinja2.contextfunction
def add_file_modal(context, title, action, upload_url, action_label):
    return new_context(modal_type='file', context=context, title=title,
                       action=action, upload_url=upload_url,
                       action_label=action_label)


@register.inclusion_tag('developers/versions/add_file_modal.html')
@jinja2.contextfunction
def add_version_modal(context, title, action, upload_url, action_label):
    return new_context(modal_type='version', context=context, title=title,
                       action=action, upload_url=upload_url,
                       action_label=action_label)


@register.function
def status_choices(addon):
    """Return a dict like STATUS_CHOICES customized for the addon status."""
    # Show "awaiting full review" for unreviewed files on that track.
    choices = dict(amo.STATUS_CHOICES)
    if addon.status in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                        amo.STATUS_PUBLIC):
        choices[amo.STATUS_UNREVIEWED] = choices[amo.STATUS_NOMINATED]
    return choices


@register.inclusion_tag('developers/versions/file_status_message.html')
def file_status_message(file, addon, file_history=False):
    choices = status_choices(addon)
    return {'fileid': file.id, 'platform': file.amo_platform.name,
            'created': jingo_datetime(file.created),
            'status': choices[file.status],
            'file_history': file_history,
            'actions': amo.LOG_REVIEW_EMAIL_USER,
            'status_date': jingo_datetime(file.datestatuschanged)}


@register.function
def dev_files_status(files, addon):
    """Group files by their status (and files per status)."""
    status_count = defaultdict(int)
    choices = status_choices(addon)

    for file in files:
        status_count[file.status] += 1

    return [(count, unicode(choices[status])) for
            (status, count) in status_count.items()]


@register.function
def mkt_status_class(addon):
    if addon.disabled_by_user and addon.status != amo.STATUS_DISABLED:
        cls = 'disabled'
    else:
        cls = amo.STATUS_CHOICES_API.get(addon.status, 'none')
    return 'status-' + cls


@register.function
def mkt_file_status_class(addon, version):
    if addon.disabled_by_user and addon.status != amo.STATUS_DISABLED:
        cls = 'disabled'
    else:
        file = version.all_files[0]
        cls = amo.STATUS_CHOICES_API.get(file.status, 'none')
    return 'status-' + cls


@register.function
def log_action_class(action_id):
    if action_id in amo.LOG_BY_ID:
        cls = amo.LOG_BY_ID[action_id].action_class
        if cls is not None:
            return 'action-' + cls


@register.function
def summarize_validation(validation):
    """Readable summary of add-on validation results."""
    # L10n: first parameter is the number of errors
    errors = ngettext('{0} error', '{0} errors',
                      validation.errors).format(validation.errors)
    # L10n: first parameter is the number of warnings
    warnings = ngettext('{0} warning', '{0} warnings',
                        validation.warnings).format(validation.warnings)
    return "%s, %s" % (errors, warnings)


@register.filter
def display_url(url):
    """Display a URL like the browser URL bar would.

    Note: returns a Unicode object, not a valid URL.
    """
    if isinstance(url, unicode):
        # Byte sequences will be url encoded so convert
        # to bytes here just to stop auto decoding.
        url = url.encode('utf8')
    bytes = urllib.unquote(url)
    c = chardet.detect(bytes)
    return bytes.decode(c['encoding'], 'replace')


@register.inclusion_tag('developers/helpers/disabled_payments_notice.html')
@jinja2.contextfunction
def disabled_payments_notice(context, addon=None):
    """
    If payments are disabled, we show a friendly message urging the developer
    to make his/her app free.
    """
    addon = context.get('addon', addon)
    return {'request': context.get('request'), 'addon': addon}


@register.function
def dev_agreement_ok(user):
    latest = settings.DEV_AGREEMENT_LAST_UPDATED
    if not latest:
        # Value not set for last updated.
        return True

    if user.is_anonymous():
        return True

    if not user.read_dev_agreement:
        # If you don't have any apps, we we won't worry about this because
        # you'll be prompted on the first submission.
        return True

    current = user.read_dev_agreement
    if current and current.date() < latest:
        # The dev agreement has been updated since you last submitted.
        return False

    return True
