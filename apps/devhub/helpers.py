from collections import defaultdict
import urllib

import chardet
import jinja2
from jingo import register
from jingo.helpers import datetime
from tower import ugettext as _, ungettext as ngettext

import amo
from amo.urlresolvers import reverse
from amo.helpers import breadcrumbs, page_title
from access import acl
from addons.helpers import new_context


register.function(acl.has_perm)


@register.inclusion_tag('devhub/addons/listing/items.html')
@jinja2.contextfunction
def dev_addon_listing_items(context, addons, src=None, notes={}):
    return new_context(**locals())


@register.function
@jinja2.contextfunction
def dev_page_title(context, title=None, addon=None):
    """Wrapper for devhub page titles."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        devhub = _('Developer Hub')
        title = '%s :: %s' % (title, devhub) if title else devhub
    return page_title(context, title)


@register.function
@jinja2.contextfunction
def dev_breadcrumbs(context, addon=None, items=None, add_default=False):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Developer Hub'
    breadcrumbs.

    **items**
        list of [(url, label)] to be inserted after Add-on.
    **addon**
        Adds the Add-on name to the end of the trail.  If items are
        specified then the Add-on will be linked.
    **add_default**
        Prepends trail back to home when True.  Default is False.
    """
    crumbs = [(reverse('devhub.index'), _('Developer Hub'))]
    if not addon and not items:
        # We are at the end of the crumb trail.
        crumbs.append((None, _('My Add-ons')))
    else:
        crumbs.append((reverse('devhub.addons'), _('My Add-ons')))
    if addon:
        if items:
            url = reverse('devhub.addons.edit', args=[addon.slug])
        else:
            # The Addon is the end of the trail.
            url = None
        crumbs.append((url, addon.name))
    if items:
        crumbs.extend(items)
    return breadcrumbs(context, crumbs, add_default)


@register.inclusion_tag('devhub/versions/add_file_modal.html')
@jinja2.contextfunction
def add_file_modal(context, title, action, upload_url, action_label):
    return new_context(modal_type='file', context=context, title=title,
                       action=action, upload_url=upload_url,
                       action_label=action_label)


@register.inclusion_tag('devhub/versions/add_file_modal.html')
@jinja2.contextfunction
def add_version_modal(context, title, action, upload_url, action_label):
    return new_context(modal_type='version', context=context, title=title,
                       action=action, upload_url=upload_url,
                       action_label=action_label)


def status_choices(addon):
    """Return a dict like STATUS_CHOICES customized for the addon status."""
    # Show "awaiting full review" for unreviewed files on that track.
    choices = dict(amo.STATUS_CHOICES)
    if addon.status in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                        amo.STATUS_PUBLIC):
        choices[amo.STATUS_UNREVIEWED] = choices[amo.STATUS_NOMINATED]
    return choices


@register.inclusion_tag('devhub/versions/file_status_message.html')
def file_status_message(file, addon):
    choices = status_choices(addon)
    return {'fileid': file.id, 'platform': file.amo_platform.name,
            'created': datetime(file.created),
            'status': choices[file.status],
            'status_date': datetime(file.datestatuschanged)}


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
def status_class(addon):
    classes = {
        amo.STATUS_NULL: 'incomplete',
        amo.STATUS_UNREVIEWED: 'unreviewed',
        amo.STATUS_NOMINATED: 'nominated',
        amo.STATUS_PUBLIC: 'fully-approved',
        amo.STATUS_DISABLED: 'admin-disabled',
        amo.STATUS_LITE: 'lite',
        amo.STATUS_LITE_AND_NOMINATED: 'lite-nom',
        amo.STATUS_PURGATORY: 'purgatory',
    }
    if addon.disabled_by_user:
        cls = 'disabled'
    else:
        cls = classes.get(addon.status, 'none')
    return 'status-' + cls


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
