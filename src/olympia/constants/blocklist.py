from enum import Enum

from olympia.amo.enum import EnumChoices


REMOTE_SETTINGS_COLLECTION_MLBF = 'addons-bloomfilters'

REASON_USER_BANNED = 'This add-on has been blocked because its author has been banned.'

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
