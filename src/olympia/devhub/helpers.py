from collections import defaultdict
import urllib

import jinja2
from jingo import register
from jingo.helpers import datetime
from django.utils.translation import ugettext as _, ungettext as ngettext
from django.utils.encoding import force_bytes

from olympia import amo
from olympia.amo.helpers import page_title
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.activity.utils import filter_queryset_to_pending_replies
from olympia.addons.helpers import new_context
from olympia.compat.models import CompatReport
from olympia.files.models import File


register.function(acl.check_addon_ownership)


@register.inclusion_tag('devhub/addons/listing/items.html')
@jinja2.contextfunction
def dev_addon_listing_items(context, addons, src=None, notes=None):
    if notes is None:
        notes = {}
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


@register.inclusion_tag('devhub/includes/source_form_field.html')
def source_form_field(field):
    return {'field': field}


@register.inclusion_tag('devhub/versions/file_status_message.html')
def file_status_message(file):
    choices = File.STATUS_CHOICES
    return {'fileid': file.id, 'platform': file.get_platform_display(),
            'created': datetime(file.created),
            'status': choices[file.status],
            'actions': amo.LOG_REVIEW_EMAIL_USER,
            'status_date': datetime(file.datestatuschanged)}


@register.function
def dev_files_status(files):
    """Group files by their status (and files per status)."""
    status_count = defaultdict(int)
    choices = File.STATUS_CHOICES

    for file in files:
        status_count[file.status] += 1

    return [(count, unicode(choices[status])) for
            (status, count) in status_count.items()]


@register.function
def status_class(addon):
    classes = {
        amo.STATUS_NULL: 'incomplete',
        amo.STATUS_NOMINATED: 'nominated',
        amo.STATUS_PUBLIC: 'approved',
        amo.STATUS_DISABLED: 'admin-disabled',
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
    url = force_bytes(url, errors='replace')
    return urllib.unquote(url).decode('utf-8', errors='replace')


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
def pending_activity_log_count_for_developer(version):
    alog = ActivityLog.objects.for_version(version).filter(
        action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)
    return filter_queryset_to_pending_replies(alog).count()
