from collections import defaultdict
import urllib

import chardet
import jinja2
from jingo import register
from jingo.helpers import datetime
from tower import ugettext as _, ungettext as ngettext

import amo
from amo.urlresolvers import reverse
from amo.helpers import breadcrumbs, impala_breadcrumbs, page_title
from access import acl
from addons.helpers import new_context
from addons.models import Addon
from compat.models import CompatReport
from files.models import File


register.function(acl.check_addon_ownership)


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
def docs_page_title(context, title=None):
    """Wrapper for docs page titles."""
    devhub = _('Add-on Documentation :: Developer Hub')
    title = '%s :: %s' % (title, devhub) if title else devhub
    return page_title(context, title)


@register.function
@jinja2.contextfunction
def dev_breadcrumbs(context, addon=None, items=None, add_default=False,
                    impala=False):
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
    **impala**
        Whether to use the impala_breadcrumbs helper. Default is False.
    """
    crumbs = [(reverse('devhub.index'), _('Developer Hub'))]
    title = _('My Submissions')
    link = reverse('devhub.addons')

    if not addon and not items:
        # We are at the end of the crumb trail.
        crumbs.append((None, title))
    else:
        crumbs.append((link, title))
    if addon:
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

    if impala:
        return impala_breadcrumbs(context, crumbs, add_default)
    else:
        return breadcrumbs(context, crumbs, add_default)


@register.function
@jinja2.contextfunction
def docs_breadcrumbs(context, items=None):
    """
    Wrapper function for `breadcrumbs` for devhub docs.
    """
    crumbs = [(reverse('devhub.index'), _('Developer Hub')),
              (None, _('Developer Docs'))]

    if items:
        crumbs.extend(items)

    return breadcrumbs(context, crumbs, True)


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


@register.inclusion_tag('devhub/includes/source_form_field.html')
def source_form_field(field):
    return {'field': field}


@register.function
def status_choices(addon):
    """
    Return a dict like File.STATUS_CHOICES customized for the addon status.
    """
    # Show "awaiting full review" for unreviewed files on that track.
    choices = dict(File.STATUS_CHOICES)
    if addon.status in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                        amo.STATUS_PUBLIC):
        choices[amo.STATUS_UNREVIEWED] = (
            Addon.STATUS_CHOICES[amo.STATUS_NOMINATED])
    else:
        choices[amo.STATUS_UNREVIEWED] = (
            Addon.STATUS_CHOICES[amo.STATUS_UNREVIEWED])
    return choices


@register.inclusion_tag('devhub/versions/file_status_message.html')
def file_status_message(file, addon, file_history=False):
    choices = status_choices(addon)
    return {'fileid': file.id, 'platform': file.get_platform_display(),
            'created': datetime(file.created),
            'status': choices[file.status],
            'file_history': file_history,
            'actions': amo.LOG_REVIEW_EMAIL_USER,
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
        amo.STATUS_DELETED: 'deleted',
        amo.STATUS_REJECTED: 'rejected',
    }
    if addon.disabled_by_user and addon.status != amo.STATUS_DISABLED:
        cls = 'disabled'
    else:
        cls = classes.get(addon.status, 'none')
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


@register.function
def get_compat_counts(addon):
    """Get counts for add-on compatibility reports."""
    return CompatReport.get_counts(addon.guid)


@register.function
def version_disabled(version):
    """Return True if all the files are disabled."""
    disabled = [status == amo.STATUS_DISABLED
                for _id, status in version.statuses]
    return all(disabled)


@register.function
def library_class(data):
    banned = data.get('banned')
    if banned is True:
        return 'library-banned'
    if banned:
        return 'library-maybe-banned'
    return ''


@register.inclusion_tag('devhub/known_library_messages.html')
def library_messages(data):
    return data
