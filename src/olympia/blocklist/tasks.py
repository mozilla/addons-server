import json
import os
import re
from datetime import datetime, timedelta
from typing import List

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.admin.options import get_content_type_for_model
from django.db import transaction
from django.utils.encoding import force_str

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import SafeStorage
from olympia.constants.blocklist import (
    MLBF_BASE_ID_CONFIG_KEY,
    MLBF_TIME_CONFIG_KEY,
    REMOTE_SETTINGS_COLLECTION_MLBF,
)
from olympia.lib.remote_settings import RemoteSettings
from olympia.zadmin.models import get_config, set_config

from .mlbf import MLBF
from .models import BlocklistSubmission, BlockType
from .utils import (
    datetime_to_ts,
)


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')


def BLOCKLIST_RECORD_MLBF_BASE(block_type: BlockType):
    match block_type:
        case BlockType.SOFT_BLOCKED:
            return 'softblocks-bloomfilter-base'
        case BlockType.BLOCKED:
            return 'bloomfilter-base'
        case _:
            raise ValueError(f'Unknown block type: {block_type}')


@task
@use_primary_db
def process_blocklistsubmission(multi_block_submit_id, **kw):
    obj = BlocklistSubmission.objects.get(pk=multi_block_submit_id)
    try:
        with transaction.atomic():
            if obj.action in BlocklistSubmission.ACTIONS.SAVE_TO_BLOCK_OBJECTS:
                # create/update the blocks from the guids in the multi_block
                obj.save_to_block_objects()
            elif obj.action in BlocklistSubmission.ACTIONS.DELETE_TO_BLOCK_OBJECTS:
                # delete/update the blocks
                obj.delete_block_objects()
    except Exception as exc:
        # If something failed reset the submission back to Pending.
        obj.update(signoff_state=BlocklistSubmission.SIGNOFF_STATES.PENDING)
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


# We rarely care about task results and ignore them by default
# (CELERY_TASK_IGNORE_RESULT=True) but here we need the result of that task to
# return it to the monitor view.
@task(ignore_result=False)
def monitor_remote_settings():
    # check Remote Settings connection
    client = RemoteSettings(
        settings.REMOTE_SETTINGS_WRITER_BUCKET,
        REMOTE_SETTINGS_COLLECTION_MLBF,
    )
    status = ''
    try:
        client.heartbeat()
    except Exception as e:
        status = f'Failed to contact Remote Settings server: {e}'
    if not status and not client.authenticated():
        status = 'Invalid credentials for Remote Settings server'
    if status:
        log.critical(status)
    return status


@task
def upload_filter(generation_time, filter_list=None, create_stash=False):
    # We cannot send enum values to tasks so we serialize them as strings
    # and deserialize them here back to the enum values.
    filter_list: List[BlockType] = (
        [] if filter_list is None else [BlockType[filter] for filter in filter_list]
    )
    bucket = settings.REMOTE_SETTINGS_WRITER_BUCKET
    server = RemoteSettings(
        bucket, REMOTE_SETTINGS_COLLECTION_MLBF, sign_off_needed=False
    )
    mlbf = MLBF.load_from_storage(generation_time, error_on_missing=True)
    is_base = len(filter_list) > 0
    # Download old records before uploading new ones
    # this ensures we do not delete any records we just uplaoded
    old_records = server.records()
    attachment_types_to_delete = []

    if is_base:
        for block_type in filter_list:
            attachment_type = BLOCKLIST_RECORD_MLBF_BASE(block_type)
            data = {
                'key_format': MLBF.KEY_FORMAT,
                'generation_time': generation_time,
                'attachment_type': attachment_type,
            }
            with mlbf.storage.open(mlbf.filter_path(block_type), 'rb') as filter_file:
                attachment = ('filter.bin', filter_file, 'application/octet-stream')
                server.publish_attachment(data, attachment)
                statsd.incr('blocklist.tasks.upload_filter.upload_mlbf')
                # After we have succesfully uploaded the new filter
                # we can safely delete others of that type
                attachment_types_to_delete.append(attachment_type)

            statsd.incr('blocklist.tasks.upload_filter.upload_mlbf.base')

    # It is possible to upload a stash and a filter in the same task
    if create_stash:
        with mlbf.storage.open(mlbf.stash_path, 'r') as stash_file:
            stash_data = json.load(stash_file)
            # If we have a stash, write that
            stash_upload_data = {
                'key_format': MLBF.KEY_FORMAT,
                'stash_time': generation_time,
                'stash': stash_data,
            }
            server.publish_record(stash_upload_data)
            statsd.incr('blocklist.tasks.upload_filter.upload_stash')

    oldest_base_filter_id: int | None = None

    # Get the oldest base_filter_id from the set of defined IDs
    # We should delete stashes that are older than this time
    for block_type in BlockType:
        # Ignore soft blocked config timestamps if the switch is not active.
        if block_type == BlockType.SOFT_BLOCKED and not waffle.switch_is_active(
            'enable-soft-blocking'
        ):
            continue

        if block_type in filter_list:
            base_filter_id = generation_time
        else:
            base_filter_id = get_config(
                # Currently we read from the old singular config key for
                # hard blocks to preserve backward compatibility.
                # In https://github.com/mozilla/addons/issues/15193
                # we can remove this and start reading from the new plural key.
                MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True),
                json_value=True,
            )

        if base_filter_id is not None:
            if oldest_base_filter_id is None:
                oldest_base_filter_id = base_filter_id
            else:
                oldest_base_filter_id = min(oldest_base_filter_id, base_filter_id)

    for record in old_records:
        # Delete attachment records that match the
        # attachment types of filters we just uplaoded
        # this ensures we only have one filter attachment
        # per block_type
        if 'attachment' in record:
            attachment_type = record['attachment_type']

            if attachment_type in attachment_types_to_delete:
                server.delete_record(record['id'])

        # Delete stash records that are older than the oldest
        # pre-existing filter attachment records. These records
        # cannot apply to any existing filter since we uploaded
        elif 'stash' in record and oldest_base_filter_id is not None:
            record_time = record['stash_time']

            if record_time < oldest_base_filter_id:
                server.delete_record(record['id'])

    # Commit the changes to remote settings for review.
    # only after any changes to records (attachments and stashes)
    # and including deletions can we commit the session
    # and update the config with the new timestamps
    server.complete_session()
    set_config(MLBF_TIME_CONFIG_KEY, generation_time, json_value=True)

    # Update the base_filter_id for uploaded filters
    for block_type in filter_list:
        # We currently write to the old singular config key for hard blocks
        # to preserve backward compatibility.
        # In https://github.com/mozilla/addons/issues/15193
        # we can remove this and start writing to the new plural key.
        if block_type == BlockType.BLOCKED:
            set_config(
                MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True),
                generation_time,
                json_value=True,
            )

        set_config(
            MLBF_BASE_ID_CONFIG_KEY(block_type), generation_time, json_value=True
        )

    cleanup_old_files.delay(base_filter_id=oldest_base_filter_id)
    statsd.incr('blocklist.tasks.upload_filter.reset_collection')


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
