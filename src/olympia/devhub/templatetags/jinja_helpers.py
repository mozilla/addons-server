from django.utils.translation import gettext, ngettext

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.activity.utils import filter_queryset_to_pending_replies
from olympia.addons.templatetags.jinja_helpers import new_context
from olympia.amo.templatetags.jinja_helpers import format_date, page_title
from olympia.files.models import File


library.global_function(acl.check_addon_ownership)


@library.global_function
@library.render_with('devhub/addons/listing/items.html')
@jinja2.pass_context
def dev_addon_listing_items(context, addons, src=None, notes=None):
    if notes is None:
        notes = {}
    return new_context(**locals())


@library.global_function
@jinja2.pass_context
def dev_page_title(context, title=None, addon=None):
    """Wrapper for devhub page titles."""
    if addon:
        title = f'{title} :: {addon.name}'
    else:
        devhub = gettext('Developer Hub')
        title = f'{title} :: {devhub}' if title else devhub
    return page_title(context, title)


@library.global_function
@library.render_with('devhub/versions/file_status_message.html')
def file_status_message(file):
    choices = File.STATUS_CHOICES
    return {
        'fileid': file.id,
        'created': format_date(file.created),
        'status': choices[file.status],
        'actions': amo.LOG_REVIEW_EMAIL_USER,
        'status_date': format_date(file.datestatuschanged),
    }


@library.global_function
def status_class(addon):
    classes = {
        amo.STATUS_NULL: 'incomplete',
        amo.STATUS_NOMINATED: 'nominated',
        amo.STATUS_APPROVED: 'approved',
        amo.STATUS_DISABLED: 'admin-disabled',
        amo.STATUS_DELETED: 'deleted',
    }
    if addon.disabled_by_user and addon.status != amo.STATUS_DISABLED:
        cls = 'disabled'
    else:
        cls = classes.get(addon.status, 'none')
    return 'status-' + cls


@library.global_function
def log_action_class(action_id):
    if action_id in amo.LOG_BY_ID:
        cls = amo.LOG_BY_ID[action_id].action_class
        if cls is not None:
            return 'action-' + cls


@library.global_function
def summarize_validation(validation):
    """Readable summary of add-on validation results."""
    # L10n: first parameter is the number of errors
    errors = ngettext('{0} error', '{0} errors', validation.errors).format(
        validation.errors
    )
    # L10n: first parameter is the number of warnings
    warnings = ngettext('{0} warning', '{0} warnings', validation.warnings).format(
        validation.warnings
    )
    return f'{errors}, {warnings}'


@library.global_function
def pending_activity_log_count_for_developer(version):
    alog = ActivityLog.objects.for_versions(version).filter(
        action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER
    )
    return filter_queryset_to_pending_replies(alog).count()
