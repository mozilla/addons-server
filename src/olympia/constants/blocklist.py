from enum import Enum

from olympia.amo.enum import EnumChoices


REMOTE_SETTINGS_COLLECTION_MLBF = 'addons-bloomfilters'

# Must be kept in sync with addons-frontend
REASON_ADDON_DELETED = 'Addon deleted'
REASON_VERSION_DELETED = 'Version deleted'


class BlockListAction(Enum):
    # Re-upload the Blocked filter
    UPLOAD_BLOCKED_FILTER = 'upload_blocked_filter'
    # Re-upload the Soft Blocked filter
    UPLOAD_SOFT_BLOCKED_FILTER = 'upload_soft_blocked_filter'
    # Upload a new stash entry
    UPLOAD_STASH = 'upload_stash'
    # Clear the Stash (clear all stashes)
    CLEAR_STASH = 'clear_stash'


class BlockType(EnumChoices):
    BLOCKED = 0, '🛑 Hard-Blocked'
    SOFT_BLOCKED = 1, '⚠️ Soft-Blocked'


class BlockReason(EnumChoices):
    FRAUD_DECEPTIVE = (
        0,
        "This add-on violates Mozilla's add-on policies by including or using "
        'deceptive, misleading, or fraudulent activity or functionality',
    )
    USER_BANNED = 1, 'This add-on has been blocked because its author has been banned.'
    ADDON_DELETED = 2, REASON_ADDON_DELETED
    VERSION_DELETED = 3, REASON_VERSION_DELETED
