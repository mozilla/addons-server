from datetime import datetime
from typing import List

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia.constants.blocklist import (
    MLBF_BASE_ID_CONFIG_KEY,
    MLBF_TIME_CONFIG_KEY,
)
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block, BlocklistSubmission, BlockType
from .tasks import process_blocklistsubmission, upload_filter
from .utils import datetime_to_ts


log = olympia.core.logger.getLogger('z.cron')


def get_generation_time():
    return datetime_to_ts()


def get_last_generation_time():
    return get_config(MLBF_TIME_CONFIG_KEY, None, json_value=True)


def get_base_generation_time(block_type: BlockType):
    return get_config(
        MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True), None, json_value=True
    )


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
    base_filters_to_update: List[BlockType] = []
    create_stash = False

    # Determine which base filters need to be re uploaded
    # and whether a new stash needs to be created.
    for block_type in BlockType:
        # This prevents us from updating a stash or filter based on new soft blocks
        # until we are ready to enable soft blocking.
        if block_type == BlockType.SOFT_BLOCKED and not waffle.switch_is_active(
            'enable-soft-blocking'
        ):
            log.info(
                'Skipping soft-blocks because enable-soft-blocking switch is inactive'
            )
            continue

        base_filter = MLBF.load_from_storage(get_base_generation_time(block_type))
        base_filters[block_type] = base_filter

        # Add this block type to the list of filters to be re-uploaded.
        if (
            force_base
            or base_filter is None
            or mlbf.should_upload_filter(block_type, base_filter)
        ):
            base_filters_to_update.append(block_type)
        # Only update the stash if we should AND if we aren't already
        # re-uploading the filter for this block type.
        elif mlbf.should_upload_stash(block_type, previous_filter or base_filter):
            create_stash = True

    skip_update = len(base_filters_to_update) == 0 and not create_stash
    if skip_update:
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

    if create_stash:
        # We generate unified stashes, which means they can contain data
        # for both soft and hard blocks. We need the base filters of each
        # block type to determine what goes in a stash.
        mlbf.generate_and_write_stash(
            previous_mlbf=previous_filter,
            blocked_base_filter=base_filters[BlockType.BLOCKED],
            soft_blocked_base_filter=base_filters[BlockType.SOFT_BLOCKED],
        )

    for block_type in base_filters_to_update:
        mlbf.generate_and_write_filter(block_type)

    upload_filter.delay(
        mlbf.created_at,
        filter_list=[key.name for key in base_filters_to_update],
        create_stash=create_stash,
    )


def process_blocklistsubmissions():
    qs = BlocklistSubmission.objects.filter(
        signoff_state__in=(
            BlocklistSubmission.SIGNOFF_STATES.STATES_APPROVED.values.keys()
        ),
        delayed_until__lte=datetime.now(),
    )
    for sub in qs:
        process_blocklistsubmission.delay(sub.id)
