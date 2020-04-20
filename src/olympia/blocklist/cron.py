import time

import waffle

import olympia.core.logger
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block
from .tasks import (
    MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY, upload_filter_to_kinto)

log = olympia.core.logger.getLogger('z.cron')


def _get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return int(latest_block.modified.timestamp() * 1000) if latest_block else 0


def upload_mlbf_to_kinto():
    if not waffle.switch_is_active('blocklist_mlbf_submit'):
        log.info('Upload MLBF to kinto cron job disabled.')
        return
    last_generation_time = get_config(MLBF_TIME_CONFIG_KEY, 0, json_value=True)
    if last_generation_time > _get_blocklist_last_modified_time():
        log.info(
            'No new/modified Blocks in database; skipping MLBF generation')
        return

    log.info('Starting Upload MLBF to kinto cron job.')

    # This timestamp represents the point in time when all previous addon
    # guid + versions and blocks were used to generate the bloomfilter.
    # An add-on version/file from before this time will definitely be accounted
    # for in the bloomfilter so we can reliably assert if it's blocked or not.
    # An add-on version/file from after this time can't be reliably asserted -
    # there may be false positives or false negatives.
    # https://github.com/mozilla/addons-server/issues/13695
    generation_time = int(time.time() * 1000)
    mlbf = MLBF(generation_time)
    mlbf.generate_and_write_mlbf()

    base_filter_id = get_config(MLBF_BASE_ID_CONFIG_KEY, 0, json_value=True)
    base_filter = MLBF(base_filter_id) if base_filter_id else None
    make_base_filter = (
        not base_filter or mlbf.should_reset_base_filter(base_filter))
    if last_generation_time and not make_base_filter:
        try:
            # optimize for when the base_filter was the previous generation so
            # we don't have to load the blocked JSON file twice.
            previous_mlbf = (
                MLBF(last_generation_time)
                if last_generation_time != base_filter_id else
                base_filter)
            mlbf.write_stash(previous_mlbf)
        except FileNotFoundError:
            log.info('No previous blocked.json so we can\'t create a stash.')
            # fallback to creating a new base if stash fails
            make_base_filter = True

    upload_filter_to_kinto.delay(
        generation_time,
        is_base=make_base_filter,
        upload_stash=not make_base_filter)
