# How many guids should there be in the stashes before we make a new base.
from enum import Enum

from olympia.blocklist.models import BlockType


BASE_REPLACE_THRESHOLD_KEY = 'blocklist_base_replace_threshold'

# Config keys used to track recent mlbf ids
MLBF_TIME_CONFIG_KEY = 'blocklist_mlbf_generation_time'


def MLBF_BASE_ID_CONFIG_KEY(block_type: BlockType, compat: bool = False):
    """
    We use compat to return the old singular config key for hard blocks.
    This allows us to migrate writes to the new plural key right now without
    losing access to the old existing key when deploying this patch.
    """
    if compat and block_type == BlockType.BLOCKED:
        return 'blocklist_mlbf_base_id'
    return f'blocklist_mlbf_base_id_{block_type.name.lower()}'


REMOTE_SETTINGS_COLLECTION_MLBF = 'addons-bloomfilters'


class BlockListAction(Enum):
    # Re-upload the Blocked filter
    UPLOAD_BLOCKED_FILTER = 'upload_blocked_filter'
    # Re-upload the Soft Blocked filter
    UPLOAD_SOFT_BLOCKED_FILTER = 'upload_soft_blocked_filter'
    # Upload a new stash entry
    UPLOAD_STASH = 'upload_stash'
    # Clear the Stash (clear all stashes)
    CLEAR_STASH = 'clear_stash'
