import json
import tempfile
import time

import waffle

import olympia.core.logger
from olympia.lib.kinto import KintoServer

from .mlbf import generate_mlbf, get_mlbf_key_format
from .utils import KINTO_BUCKET, KINTO_COLLECTION_MLBF

log = olympia.core.logger.getLogger('z.cron')


def upload_mlbf_to_kinto():
    if not waffle.switch_is_active('blocklist_mlbf_submit'):
        log.info('Upload MLBF to kinto cron job disabled.')
        return
    log.info('Starting Upload MLBF to kinto cron job.')
    server = KintoServer(
        KINTO_BUCKET, KINTO_COLLECTION_MLBF, kinto_sign_off_needed=False)
    stats = {}
    key_format = get_mlbf_key_format()
    generation_time = int(time.time() * 1000)
    bloomfilter = generate_mlbf(stats, key_format)
    with tempfile.NamedTemporaryFile() as filter_file:
        bloomfilter.tofile(filter_file)
        filter_file.seek(0)
        data = {
            'key_format': key_format,
            'generation_time': generation_time,
        }
        attachment = ('filter.bin', filter_file, 'application/octet-stream')
        server.publish_attachment(data, attachment)
    server.complete_session()
    log.info(json.dumps(stats))
