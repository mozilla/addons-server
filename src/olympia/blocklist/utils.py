from olympia import amo
from olympia.activity import log_create


def add_to_latest_version_in_channel(obj, al, channel):
    from olympia.activity.models import VersionLog

    version_ids = [
        id_ for id_, chan in obj.addon_versions.values()
        if chan == channel]
    if not version_ids:
        return
    VersionLog.objects.create(activity_log=al, version_id=version_ids[-1])


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

    add_to_latest_version_in_channel(obj, al, amo.RELEASE_CHANNEL_LISTED)
    add_to_latest_version_in_channel(obj, al, amo.RELEASE_CHANNEL_UNLISTED)


def block_activity_log_delete(obj, user):
    al = log_create(
        amo.LOG.BLOCKLIST_BLOCK_DELETED, obj.addon, obj.guid, obj,
        details={'guid': obj.guid}, user=user)

    add_to_latest_version_in_channel(obj, al, amo.RELEASE_CHANNEL_LISTED)
    add_to_latest_version_in_channel(obj, al, amo.RELEASE_CHANNEL_UNLISTED)
