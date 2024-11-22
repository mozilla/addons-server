# How many guids should there be in the stashes before we make a new base.
from olympia.blocklist.models import BlockType


BASE_REPLACE_THRESHOLD = 5_000

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
