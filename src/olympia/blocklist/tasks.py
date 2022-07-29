import os
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.admin.options import get_content_type_for_model
from django.db import transaction
from django.utils.encoding import force_str

from django_statsd.clients import statsd

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import SafeStorage
from olympia.constants.blocklist import (
    MLBF_TIME_CONFIG_KEY,
    MLBF_BASE_ID_CONFIG_KEY,
    REMOTE_SETTINGS_COLLECTION_MLBF,
)
from olympia.lib.remote_settings import RemoteSettings
from olympia.zadmin.models import set_config

from .mlbf import MLBF
from .models import BlocklistSubmission
from .utils import (
    datetime_to_ts,
)


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')

BLOCKLIST_RECORD_MLBF_BASE = 'bloomfilter-base'


@task
@use_primary_db
def process_blocklistsubmission(multi_block_submit_id, **kw):
    obj = BlocklistSubmission.objects.get(pk=multi_block_submit_id)
    try:
        with transaction.atomic():
            if obj.action == BlocklistSubmission.ACTION_ADDCHANGE:
                # create the blocks from the guids in the multi_block
                obj.save_to_block_objects()
            elif obj.action == BlocklistSubmission.ACTION_DELETE:
                # delete the blocks
                obj.delete_block_objects()
    except Exception as exc:
        # If something failed reset the submission back to Pending.
        obj.update(signoff_state=BlocklistSubmission.SIGNOFF_PENDING)
        message = f'Exception in task: {exc}'
        LogEntry.objects.log_action(
            user_id=settings.TASK_USER_ID,
            content_type_id=get_content_type_for_model(obj).pk,
            object_id=obj.pk,
            object_repr=str(obj),
            action_flag=CHANGE,
            change_message=message,
        )
        raise exc


@task
def upload_filter(generation_time, is_base=True):
    bucket = settings.REMOTE_SETTINGS_WRITER_BUCKET
    server = RemoteSettings(
        bucket, REMOTE_SETTINGS_COLLECTION_MLBF, sign_off_needed=False
    )
    mlbf = MLBF.load_from_storage(generation_time)
    if is_base:
        # clear the collection for the base - we want to be the only filter
        server.delete_all_records()
        statsd.incr('blocklist.tasks.upload_filter.reset_collection')
        # Then the bloomfilter
        data = {
            'key_format': MLBF.KEY_FORMAT,
            'generation_time': generation_time,
            'attachment_type': BLOCKLIST_RECORD_MLBF_BASE,
        }
        storage = SafeStorage(root_setting='MLBF_STORAGE_PATH')
        with storage.open(mlbf.filter_path, 'rb') as filter_file:
            attachment = ('filter.bin', filter_file, 'application/octet-stream')
            server.publish_attachment(data, attachment)
            statsd.incr('blocklist.tasks.upload_filter.upload_mlbf')
        statsd.incr('blocklist.tasks.upload_filter.upload_mlbf.base')
    else:
        # If we have a stash, write that
        stash_data = {
            'key_format': MLBF.KEY_FORMAT,
            'stash_time': generation_time,
            'stash': mlbf.stash_json,
        }
        server.publish_record(stash_data)
        statsd.incr('blocklist.tasks.upload_filter.upload_stash')

    server.complete_session()
    set_config(MLBF_TIME_CONFIG_KEY, generation_time, json_value=True)
    if is_base:
        set_config(MLBF_BASE_ID_CONFIG_KEY, generation_time, json_value=True)


@task
def cleanup_old_files(*, base_filter_id):
    log.info('Starting clean up of old MLBF folders...')
    six_months_ago = datetime_to_ts(datetime.now() - timedelta(weeks=26))
    base_filter_ts = int(base_filter_id)
    storage = SafeStorage(root_setting='MLBF_STORAGE_PATH')
    for dir in storage.listdir(settings.MLBF_STORAGE_PATH)[0]:
        dir = force_str(dir)
        # skip non-numeric folder names
        if not dir.isdigit():
            log.info('Skipping %s because not a timestamp', dir)
            continue
        dir_ts = int(dir)
        dir_as_date = datetime.fromtimestamp(dir_ts / 1000)
        # delete if >6 months old and <base_filter_id
        if dir_ts > six_months_ago:
            log.info('Skipping %s because < 6 months old (%s)', dir, dir_as_date)
        elif dir_ts > base_filter_ts:
            log.info(
                'Skipping %s because more recent (%s) than base mlbf (%s)',
                dir,
                dir_as_date,
                datetime.fromtimestamp(base_filter_ts / 1000),
            )
        else:
            log.info('Deleting %s because > 6 months old (%s)', dir, dir_as_date)
            storage.rm_stored_dir(os.path.join(settings.MLBF_STORAGE_PATH, dir))
