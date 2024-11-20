from datetime import datetime

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia.constants.blocklist import (
    BASE_REPLACE_THRESHOLD,
    MLBF_BASE_ID_CONFIG_KEY,
    MLBF_TIME_CONFIG_KEY,
)
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block, BlocklistSubmission, BlockType
from .tasks import cleanup_old_files, process_blocklistsubmission, upload_filter
from .utils import datetime_to_ts


log = olympia.core.logger.getLogger('z.cron')


def get_generation_time():
    return datetime_to_ts()


def get_last_generation_time():
    return get_config(MLBF_TIME_CONFIG_KEY, None, json_value=True)


def get_base_generation_time():
    return get_config(MLBF_BASE_ID_CONFIG_KEY, None, json_value=True)


def get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return datetime_to_ts(latest_block.modified) if latest_block else 0


def upload_mlbf_to_remote_settings(*, bypass_switch=False, force_base=False):
    """Creates a bloomfilter, and possibly a stash json blob, and uploads to
    remote-settings.
    bypass_switch=<Truthy value> will bypass the "enable-soft-blocking" switch
    for manual use/testing.
    force_base=<Truthy value> will force a new base MLBF and a reset of the
    collection.
    """
    bypass_switch = bool(bypass_switch)
    if not (bypass_switch or waffle.switch_is_active('enable-soft-blocking')):
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
    generation_time = get_generation_time()
    # This timestamp represents the last time the MLBF was generated and uploaded.
    # It could have been a base filter or a stash.
    last_generation_time = get_last_generation_time()
    # This timestamp represents the point in time when
    # the base filter was generated and uploaded.
    base_generation_time = get_base_generation_time()

    mlbf = MLBF.generate_from_db(generation_time)

    base_filter = (
        MLBF.load_from_storage(base_generation_time)
        if base_generation_time is not None
        else None
    )

    previous_filter = (
        # Only load previoous filter if there is a timestamp to use
        # and that timestamp is not the same as the base_filter
        MLBF.load_from_storage(last_generation_time)
        if last_generation_time is not None
        and (base_filter is None or base_filter.created_at != last_generation_time)
        else base_filter
    )

    changes_count = mlbf.blocks_changed_since_previous(
        BlockType.BLOCKED, previous_filter
    )
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.blocked_changed', changes_count
    )
    need_update = (
        force_base
        or base_filter is None
        or (
            previous_filter is not None
            and previous_filter.created_at < get_blocklist_last_modified_time()
        )
        or changes_count > 0
    )
    if not need_update:
        log.info('No new/modified/deleted Blocks in database; skipping MLBF generation')
        return

    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.blocked_count',
        len(mlbf.data.blocked_items),
    )
    statsd.incr(
        'blocklist.cron.upload_mlbf_to_remote_settings.not_blocked_count',
        len(mlbf.data.not_blocked_items),
    )

    make_base_filter = (
        force_base
        or base_filter is None
        or previous_filter is None
        or mlbf.blocks_changed_since_previous(BlockType.BLOCKED, base_filter)
        > BASE_REPLACE_THRESHOLD
    )

    if make_base_filter:
        mlbf.generate_and_write_filter()
    else:
        mlbf.generate_and_write_stash(previous_filter)

    upload_filter.delay(generation_time, is_base=make_base_filter)

    if base_filter:
        cleanup_old_files.delay(base_filter_id=base_filter.created_at)


def process_blocklistsubmissions():
    qs = BlocklistSubmission.objects.filter(
        signoff_state__in=(
            BlocklistSubmission.SIGNOFF_STATES.STATES_APPROVED.values.keys()
        ),
        delayed_until__lte=datetime.now(),
    )
    for sub in qs:
        process_blocklistsubmission.delay(sub.id)
