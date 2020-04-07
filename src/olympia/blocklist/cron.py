import json
import os
import time

from django.conf import settings
from django.core.files.storage import default_storage as storage

import waffle

import olympia.core.logger
from olympia.zadmin.models import get_config

from . import tasks
from .mlbf import generate_mlbf
from .models import Block

log = olympia.core.logger.getLogger('z.cron')


def _get_blocklist_last_modified_time():
    latest_block = Block.objects.order_by('-modified').first()
    return int(latest_block.modified.timestamp() * 1000) if latest_block else 0


def upload_mlbf_to_kinto():
    if not waffle.switch_is_active('blocklist_mlbf_submit'):
        log.info('Upload MLBF to kinto cron job disabled.')
        return
    last_generation_time = get_config(
        tasks.MLBF_TIME_CONFIG_KEY, 0, json_value=True)
    if last_generation_time > _get_blocklist_last_modified_time():
        log.info(
            'No new/modified Blocks in database; skipping MLBF generation')
        return

    log.info('Starting Upload MLBF to kinto cron job.')
    stats = {}

    # This timestamp represents the point in time when all previous addon
    # guid + versions and blocks were used to generate the bloomfilter.
    # An add-on version/file from before this time will definitely be accounted
    # for in the bloomfilter so we can reliably assert if it's blocked or not.
    # An add-on version/file from after this time can't be reliably asserted -
    # there may be false positives or false negatives.
    # https://github.com/mozilla/addons-server/issues/13695
    generation_time = int(time.time() * 1000)
    bloomfilter = generate_mlbf(stats)
    mlbf_path = os.path.join(
        settings.MLBF_STORAGE_PATH, f'{generation_time}.filter')
    with storage.open(mlbf_path, 'wb') as filter_file:
        bloomfilter.tofile(filter_file)
    tasks.upload_mlbf_to_kinto.delay(generation_time)
    log.info(json.dumps(stats))
