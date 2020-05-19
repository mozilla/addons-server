import time

from django.core.management import call_command
from django.core.management.base import CommandError

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia.constants.blocklist import (
    MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY)
from olympia.zadmin.models import get_config

from .mlbf import MLBF
from .models import Block
from .tasks import upload_filter_to_kinto


log = olympia.core.logger.getLogger('z.cron')


def get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return int(latest_block.modified.timestamp() * 1000) if latest_block else 0


def upload_mlbf_to_kinto(*, bypass_switch=False):
    """Creates a bloomfilter, and possibly a stash json blob, and uploads to
    remote-settings.
    bypass_switch=<Truthy value> will bypass the "blocklist_mlbf_submit" switch
    for manual use/testing."""
    bypass_switch = bool(bypass_switch)
    if not (bypass_switch or waffle.switch_is_active('blocklist_mlbf_submit')):
        log.info('Upload MLBF to kinto cron job disabled.')
        return
    last_generation_time = get_config(MLBF_TIME_CONFIG_KEY, 0, json_value=True)

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
    previous_filter = MLBF(last_generation_time)

    need_mlbf = (
        last_generation_time < get_blocklist_last_modified_time() or
        mlbf.blocks_changed_since_previous(previous_filter))
    if not need_mlbf:
        log.info(
            'No new/modified/deleted Blocks in database; '
            'skipping MLBF generation')
        return

    mlbf.generate_and_write_mlbf()

    base_filter_id = get_config(MLBF_BASE_ID_CONFIG_KEY, 0, json_value=True)
    # optimize for when the base_filter was the previous generation so
    # we don't have to load the blocked JSON file twice.
    base_filter = (
        MLBF(base_filter_id)
        if last_generation_time != base_filter_id else
        previous_filter)

    make_base_filter = (
        not base_filter or mlbf.should_reset_base_filter(base_filter))
    if last_generation_time and not make_base_filter:
        try:
            mlbf.write_stash(previous_filter)
        except FileNotFoundError:
            log.info('No previous blocked.json so we can\'t create a stash.')
            # fallback to creating a new base if stash fails
            make_base_filter = True

    upload_filter_to_kinto.delay(
        generation_time,
        is_base=make_base_filter,
        upload_stash=not make_base_filter)


def auto_import_blocklist():
    if not waffle.switch_is_active('blocklist_auto_import'):
        log.info('Automatic import_blocklist cron job disabled.')
        return
    with statsd.timer('blocklist.cron.import_blocklist'):
        try:
            call_command('import_blocklist')
        except CommandError as err:
            statsd.incr('blocklist.cron.import_blocklist.failure')
            raise err
    statsd.incr('blocklist.cron.import_blocklist.success')
