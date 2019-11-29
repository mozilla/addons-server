from olympia import amo
from olympia.activity import log_create


def add_version_log_for_blocked_versions(obj, al):
    from olympia.activity.models import VersionLog

    VersionLog.objects.bulk_create([
        VersionLog(activity_log=al, version_id=id_chan[0])
        for version, id_chan in obj.addon_versions.items()
        if obj.is_version_blocked(version)
    ])


def block_activity_log_save(obj, change):
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
    al = log_create(
        action, obj.addon, obj.guid, obj, details=details, user=obj.updated_by)

    add_version_log_for_blocked_versions(obj, al)


def block_activity_log_delete(obj, user):
    al = log_create(
        amo.LOG.BLOCKLIST_BLOCK_DELETED, obj.addon, obj.guid, obj,
        details={'guid': obj.guid}, user=user)

    add_version_log_for_blocked_versions(obj, al)
