import olympia.core.logger
from olympia import amo
from olympia.activity import log_create
from olympia.lib.kinto import KintoServer


log = olympia.core.logger.getLogger('z.amo.blocklist')

KINTO_BUCKET = 'staging'
KINTO_COLLECTION_LEGACY = 'addons'
KINTO_COLLECTION_MLBF = 'addons-mlbf'


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


def block_activity_log_delete(obj, submission_obj):
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
    args = (
        [amo.LOG.BLOCKLIST_BLOCK_DELETED] +
        ([obj.addon] if obj.addon else []) +
        [obj.guid, obj])
    al = log_create(
        *args, details=details, user=submission_obj.updated_by)
    if obj.addon:
        add_version_log_for_blocked_versions(obj, al)
    if submission_obj.signoff_by:
        args = (
            [amo.LOG.BLOCKLIST_SIGNOFF] +
            ([obj.addon] if obj.addon else []) +
            [obj.guid, amo.LOG.BLOCKLIST_BLOCK_DELETED.action_class, obj])
        log_create(*args, user=submission_obj.signoff_by)


def splitlines(text):
    return [line.strip() for line in str(text or '').splitlines()]


def legacy_publish_blocks(blocks):
    server = KintoServer(KINTO_BUCKET, KINTO_COLLECTION_LEGACY)
    for block in blocks:
        needs_updating = block.include_in_legacy and block.kinto_id
        needs_creating = block.include_in_legacy and not block.kinto_id
        needs_deleting = block.kinto_id and not block.include_in_legacy

        if needs_updating or needs_creating:
            if block.is_imported_from_kinto_regex:
                log.debug(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    'can\'t be safely updated.  Skipping.')
                continue
            data = {
                'guid': block.guid,
                'details': {
                    'bug': block.url,
                    'why': block.reason,
                    'name': str(block.reason).partition('.')[0],  # required
                },
                'enabled': True,
                'versionRange': [{
                    'severity': 3,  # Always high severity now.
                    'minVersion': block.min_version,
                    'maxVersion': block.max_version,
                }],
            }
            if needs_creating:
                record = server.publish_record(data)
                block.update(kinto_id=record.get('id', ''))
            else:
                server.publish_record(data, block.kinto_id)
        elif needs_deleting:
            if block.is_imported_from_kinto_regex:
                log.debug(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    'can\'t be safely deleted.  Skipping.')
            else:
                server.delete_record(block.kinto_id)
            block.update(kinto_id='')
        # else no existing kinto record and it shouldn't be in legacy so skip
    server.signoff_request()


def legacy_delete_blocks(blocks):
    server = KintoServer(KINTO_BUCKET, KINTO_COLLECTION_LEGACY)
    for block in blocks:
        if block.kinto_id and block.include_in_legacy:
            if block.is_imported_from_kinto_regex:
                log.debug(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    'can\'t be safely deleted.  Skipping.')
            else:
                server.delete_record(block.kinto_id)
            block.update(kinto_id='')
    server.signoff_request()
