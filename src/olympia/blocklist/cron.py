from datetime import datetime

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.constants.blocklist import BlockListAction
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block, BlocklistSubmission, BlockType
from .tasks import process_blocklistsubmission, upload_filter
from .utils import datetime_to_ts, get_mlbf_base_id_config_key


log = olympia.core.logger.getLogger('z.cron')


def get_generation_time():
    return datetime_to_ts()


def get_last_generation_time():
    return get_config(amo.config_keys.BLOCKLIST_MLBF_TIME)


def get_base_generation_time(block_type: BlockType):
    return get_config(get_mlbf_base_id_config_key(block_type, compat=True))


def get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return datetime_to_ts(latest_block.modified) if latest_block else 0


def upload_mlbf_to_remote_settings(*, bypass_switch=False, force_base=False):
    """Creates a bloomfilter, and possibly a stash json blob, and uploads to
    remote-settings.
    bypass_switch=<Truthy value> will bypass the "blocklist_mlbf_submit" switch
    for manual use/testing.
    force_base=<Truthy value> will force a new base MLBF and a reset of the
    collection.
    """
    bypass_switch = bool(bypass_switch)
    if not (bypass_switch or waffle.switch_is_active('blocklist_mlbf_submit')):
        log.info('Upload MLBF to remote settings cron job disabled.')
        return
    with statsd.timer('blocklist.cron.upload_mlbf_to_remote_settings'):
        _upload_mlbf_to_remote_settings(force_base=bool(force_base))
    statsd.incr('blocklist.cron.upload_mlbf_to_remote_settings.success')


def _upload_mlbf_to_remote_settings(*, force_base=False):
    log.info('Starting Upload MLBF to remote settings cron job.')

    # This timestamp represents the point in time when all previous addon
    # guid + versions and blocks were used to generate the bloomfilter.
    # An add-on version/file from before this time will definitely be accounted
    # for in the bloomfilter so we can reliably assert if it's blocked or not.
    # An add-on version/file from after this time can't be reliably asserted -
    # there may be false positives or false negatives.
    # https://github.com/mozilla/addons-server/issues/13695
    mlbf = MLBF.generate_from_db(get_generation_time())
    previous_filter = MLBF.load_from_storage(
        # This timestamp represents the last time the MLBF was generated and uploaded.
        # It could have been a base filter or a stash.
        get_last_generation_time()
    )

    base_filters: dict[BlockType, MLBF | None] = {key: None for key in BlockType}

    upload_filters = False
    upload_stash = False

    # Determine which base filters need to be re uploaded
    # and whether a new stash needs to be created.
    for block_type in BlockType:
        base_filter = MLBF.load_from_storage(get_base_generation_time(block_type))
        base_filters[block_type] = base_filter

        # For now we upload both filters together when either exceeds
        # the change threshold. Additionally we brute force clear all stashes
        # when uploading filters. This is the easiest way to ensure that stashes
        # are always newer than any existing filters, a requirement of the way
        # FX is reading the blocklist stash and filter sets.
        # We may attempt handling block types separately in the future as a
        # performance optimization https://github.com/mozilla/addons/issues/15217.
        if (
            force_base
            or base_filter is None
            or mlbf.should_upload_filter(block_type, base_filter)
        ):
            upload_filters = True
            upload_stash = False
        # Only update the stash if we should AND if we aren't already
        # re-uploading the filters.
        elif mlbf.should_upload_stash(block_type, previous_filter or base_filter):
            upload_stash = True

    if not upload_filters and not upload_stash:
        log.info('No new/modified/deleted Blocks in database; skipping MLBF generation')
        # Delete the locally generated MLBF directory and files as they are not needed.
        mlbf.delete()
        return

    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.blocked_count',
        len(mlbf.data.blocked_items),
    )
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.soft_blocked_count',
        len(mlbf.data.soft_blocked_items),
    )
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.not_blocked_count',
        len(mlbf.data.not_blocked_items),
    )

    if upload_filters:
        for block_type in BlockType:
            mlbf.generate_and_write_filter(block_type)

        # Upload both filters and clear the stash to keep
        # all of the records in sync with the expectations of FX.
        actions = [
            BlockListAction.UPLOAD_BLOCKED_FILTER,
            BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER,
            BlockListAction.CLEAR_STASH,
        ]

    elif upload_stash:
        # We generate unified stashes, which means they can contain data
        # for both soft and hard blocks. We need the base filters of each
        # block type to determine what goes in a stash.
        mlbf.generate_and_write_stash(
            previous_mlbf=previous_filter,
            blocked_base_filter=base_filters[BlockType.BLOCKED],
            soft_blocked_base_filter=base_filters[BlockType.SOFT_BLOCKED],
        )
        actions = [
            BlockListAction.UPLOAD_STASH,
        ]

    # Serialize the actions to strings because celery doesn't support enums.
    upload_filter.delay(mlbf.created_at, actions=[action.name for action in actions])


def process_blocklistsubmissions():
    qs = BlocklistSubmission.objects.filter(
        signoff_state__in=(BlocklistSubmission.SIGNOFF_STATES.STATES_APPROVED.values),
        delayed_until__lte=datetime.now(),
    )
    for sub in qs:
        process_blocklistsubmission.delay(sub.id)
