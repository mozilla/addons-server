from django.utils.html import format_html, conditional_escape
from django.utils.safestring import mark_safe

from olympia import amo
from olympia.activity import log_create


def add_version_log_for_blocked_versions(obj, al):
    from olympia.activity.models import VersionLog

    VersionLog.objects.bulk_create([
        VersionLog(activity_log=al, version_id=id_chan[0])
        for version, id_chan in obj.addon_versions.items()
        if obj.is_version_blocked(version)
    ])


def block_activity_log_save(obj, change, submission_obj=None):
    action = (
        amo.LOG.BLOCKLIST_BLOCK_EDITED if change else
        amo.LOG.BLOCKLIST_BLOCK_ADDED)
    details = {
        'guid': obj.guid,
        'min_version': obj.min_version,
        'max_version': obj.max_version,
        'url': obj.url,
        'reason': obj.reason,
        'include_in_legacy': obj.include_in_legacy,
        'comments': f'Versions {obj.min_version} - {obj.max_version} blocked.',
    }
    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state)
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    al = log_create(
        action, obj.addon, obj.guid, obj, details=details, user=obj.updated_by)
    if submission_obj and submission_obj.signoff_by:
        log_create(
            amo.LOG.BLOCKLIST_SIGNOFF,
            obj.addon,
            obj.guid,
            action.action_class,
            obj,
            user=submission_obj.signoff_by)

    add_version_log_for_blocked_versions(obj, al)


def block_activity_log_delete(obj, user):
    args = (
        [amo.LOG.BLOCKLIST_BLOCK_DELETED] +
        ([obj.addon] if obj.addon else []) +
        [obj.guid, obj])
    al = log_create(
        *args, details={'guid': obj.guid}, user=user)
    if obj.addon:
        add_version_log_for_blocked_versions(obj, al)


def format_block_history(logs):
    def format_html_join_kw(sep, format_string, kwargs_generator):
        return mark_safe(conditional_escape(sep).join(
            format_html(format_string, **kwargs)
            for kwargs in kwargs_generator
        ))

    history_format_string = (
        '<li>'
        '{date}. {action} by {name}: {guid}{versions}. {legacy}'
        '<ul><li>{reason}</li></ul>'
        '</li>')
    guid_url_format_string = '<a href="{url}">{text}</a>'
    versions_format_string = ', versions {min} - {max}'

    log_entries_gen = (
        {'date': (
            format_html(
                guid_url_format_string,
                url=log.details.get('url'),
                text=log.created.date())
            if log.details.get('url') else log.created.date()),
         'action': amo.LOG_BY_ID[log.action].short,
         'name': log.author_name,
         'guid': log.details.get('guid'),
         'versions': (
            format_html(
                versions_format_string, **{
                    'min': log.details.get('min_version'),
                    'max': log.details.get('max_version')})
            if 'min_version' in log.details else ''),
         'legacy': (
            'Included in legacy blocklist.'
            if log.details.get('include_in_legacy') else ''),
         'reason': log.details.get('reason') or ''}
        for log in logs)
    return format_html(
        '<ul>\n{}\n</ul>',
        format_html_join_kw('\n', history_format_string, log_entries_gen))


def splitlines(text):
    return [line.strip() for line in str(text or '').splitlines()]
