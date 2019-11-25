from olympia import amo
from olympia.activity import log_create


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
    }
    log_create(
        action, obj.addon, obj.guid, obj, details=details, user=obj.updated_by)


def block_activity_log_delete(obj, user):
    log_create(
        amo.LOG.BLOCKLIST_BLOCK_DELETED, obj.addon, obj.guid, obj,
        details={'guid': obj.guid}, user=user)
