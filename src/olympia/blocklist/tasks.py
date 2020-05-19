import re
import time
from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction

from django_statsd.clients import statsd
from multidb import get_replica

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.constants.blocklist import (
    MLBF_TIME_CONFIG_KEY,
    MLBF_BASE_ID_CONFIG_KEY,
    REMOTE_SETTINGS_COLLECTION_MLBF)
from olympia.files.models import File
from olympia.lib.kinto import KintoServer
from olympia.users.utils import get_task_user
from olympia.zadmin.models import set_config

from .mlbf import MLBF
from .models import Block, BlocklistSubmission, KintoImport
from .utils import (
    block_activity_log_delete, block_activity_log_save, split_regex_to_list)


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')

BLOCKLIST_RECORD_MLBF_BASE = 'bloomfilter-base'
BLOCKLIST_RECORD_MLBF_UPDATE = 'bloomfilter-full'


@task
@use_primary_db
def process_blocklistsubmission(multi_block_submit_id, **kw):
    obj = BlocklistSubmission.objects.get(pk=multi_block_submit_id)
    if obj.action == BlocklistSubmission.ACTION_ADDCHANGE:
        # create the blocks from the guids in the multi_block
        obj.save_to_block_objects()
    elif obj.action == BlocklistSubmission.ACTION_DELETE:
        # delete the blocks
        obj.delete_block_objects()


@task
@use_primary_db
@transaction.atomic
def import_block_from_blocklist(record):
    kinto_id = record.get('id')
    using_db = get_replica()
    log.info('Processing block id: [%s]', kinto_id)
    kinto_import, import_created = KintoImport.objects.update_or_create(
        kinto_id=kinto_id,
        defaults={'record': record, 'timestamp': record.get('last_modified')})
    if not import_created:
        log.info('Kinto %s: updating existing KintoImport object', kinto_id)
        existing_block_ids = list(
            Block.objects.filter(kinto_id__in=(kinto_id, f'*{kinto_id}'))
                         .values_list('id', flat=True))

    guid = record.get('guid')
    if not guid:
        kinto_import.outcome = KintoImport.OUTCOME_MISSINGGUID
        kinto_import.save()
        log.error('Kinto %s: GUID is falsey, skipping.', kinto_id)
        return
    version_range = record.get('versionRange', [{}])[0]
    target_application = version_range.get('targetApplication') or [{}]
    target_GUID = target_application[0].get('guid')
    if target_GUID and target_GUID != amo.FIREFOX.guid:
        kinto_import.outcome = KintoImport.OUTCOME_NOTFIREFOX
        kinto_import.save()
        log.error(
            'Kinto %s: targetApplication (%s) is not Firefox, skipping.',
            kinto_id, target_GUID)
        return
    block_kw = {
        'min_version': version_range.get('minVersion', '0'),
        'max_version': version_range.get('maxVersion', '*'),
        'url': record.get('details', {}).get('bug') or '',
        'reason': record.get('details', {}).get('why') or '',
        'kinto_id': kinto_id,
        'include_in_legacy': True,
        'updated_by': get_task_user(),
    }
    modified_date = datetime.fromtimestamp(
        record.get('last_modified', time.time() * 1000) / 1000)

    if guid.startswith('/'):
        # need to escape the {} brackets or mysql chokes.
        guid_regexp = bracket_open_regex.sub(r'\{', guid[1:-1])
        guid_regexp = bracket_close_regex.sub(r'\}', guid_regexp)
        # we're going to try to split the regex into a list for efficiency.
        guids_list = split_regex_to_list(guid_regexp)
        if guids_list:
            log.info(
                'Kinto %s: Broke down regex into list; '
                'attempting to create Blocks for guids in %s',
                kinto_id, guids_list)
            statsd.incr(
                'blocklist.tasks.import_blocklist.record_guid',
                count=len(guids_list))
            addons_guids_qs = Addon.unfiltered.using(using_db).filter(
                guid__in=guids_list).values_list('guid', flat=True)
        else:
            log.info(
                'Kinto %s: Unable to break down regex into list; '
                'attempting to create Blocks for guids matching [%s]',
                kinto_id, guid_regexp)
            # mysql doesn't support \d - only [:digit:]
            guid_regexp = guid_regexp.replace(r'\d', '[[:digit:]]')
            addons_guids_qs = Addon.unfiltered.using(using_db).filter(
                guid__regex=guid_regexp).values_list('guid', flat=True)
        # We need to mark this id in a way so we know its from a
        # regex guid - otherwise we might accidentally overwrite it.
        block_kw['kinto_id'] = '*' + block_kw['kinto_id']
        regex = True
    else:
        log.info(
            'Kinto %s: Attempting to create a Block for guid [%s]',
            kinto_id, guid)
        statsd.incr('blocklist.tasks.import_blocklist.record_guid')
        addons_guids_qs = Addon.unfiltered.using(using_db).filter(
            guid=guid).values_list('guid', flat=True)
        regex = False
    new_blocks = []
    for guid in addons_guids_qs:
        valid_files_qs = File.objects.filter(
            version__addon__guid=guid, is_webextension=True)
        if not valid_files_qs.exists():
            log.info(
                'Kinto %s: Skipped Block for [%s] because it has no '
                'webextension files', kinto_id, guid)
            statsd.incr('blocklist.tasks.import_blocklist.block_skipped')
            continue
        (block, created) = Block.objects.update_or_create(
            guid=guid, defaults=dict(guid=guid, **block_kw))
        block_activity_log_save(block, change=not created)
        if created:
            log.info('Kinto %s: Added Block for [%s]', kinto_id, guid)
            statsd.incr('blocklist.tasks.import_blocklist.block_added')
            block.update(modified=modified_date)
        else:
            log.info('Kinto %s: Updated Block for [%s]', kinto_id, guid)
            statsd.incr('blocklist.tasks.import_blocklist.block_updated')
        new_blocks.append(block)
    if new_blocks:
        kinto_import.outcome = (
            KintoImport.OUTCOME_REGEXBLOCKS if regex else
            KintoImport.OUTCOME_BLOCK
        )
    else:
        kinto_import.outcome = KintoImport.OUTCOME_NOMATCH
        log.info('Kinto %s: No addon found', kinto_id)
    if not import_created:
        # now reconcile the blocks that were connected to the import last time
        # but weren't changed this time - i.e. blocks we need to delete
        delete_qs = (
            Block.objects.filter(id__in=existing_block_ids)
                         .exclude(id__in=(block.id for block in new_blocks)))
        for block in delete_qs:
            block_activity_log_delete(
                block, delete_user=block_kw['updated_by'])
            block.delete()
            statsd.incr('blocklist.tasks.import_blocklist.block_deleted')

    kinto_import.save()

    if import_created:
        statsd.incr(
            'blocklist.tasks.import_blocklist.new_record_processed')
    else:
        statsd.incr(
            'blocklist.tasks.import_blocklist.modified_record_processed')


@task
@use_primary_db
@transaction.atomic
def delete_imported_block_from_blocklist(kinto_id):
    existing_blocks = (
        Block.objects.filter(kinto_id__in=(kinto_id, f'*{kinto_id}')))
    task_user = get_task_user()
    for block in existing_blocks:
        block_activity_log_delete(
            block, delete_user=task_user)
        block.delete()
        statsd.incr('blocklist.tasks.import_blocklist.block_deleted')
    KintoImport.objects.get(kinto_id=kinto_id).delete()
    statsd.incr('blocklist.tasks.import_blocklist.deleted_record_processed')


@task
def upload_filter_to_kinto(generation_time, is_base=True, upload_stash=False):
    bucket = settings.REMOTE_SETTINGS_WRITER_BUCKET
    server = KintoServer(
        bucket, REMOTE_SETTINGS_COLLECTION_MLBF, kinto_sign_off_needed=False)
    mlbf = MLBF(generation_time)
    if is_base:
        # clear the collection for the base - we want to be the only filter
        server.delete_all_records()
    # Deal with possible stashes first
    if upload_stash:
        # If we have a stash, write that
        stash_data = {
            'key_format': MLBF.KEY_FORMAT,
            'stash_time': generation_time,
            'stash': mlbf.stash_json,
        }
        server.publish_record(stash_data)

    # Then the bloomfilter
    data = {
        'key_format': MLBF.KEY_FORMAT,
        'generation_time': generation_time,
        'attachment_type':
            BLOCKLIST_RECORD_MLBF_BASE if is_base else
            BLOCKLIST_RECORD_MLBF_UPDATE,
    }
    with storage.open(mlbf.filter_path, 'rb') as filter_file:
        attachment = ('filter.bin', filter_file, 'application/octet-stream')
        server.publish_attachment(data, attachment)
    server.complete_session()
    set_config(MLBF_TIME_CONFIG_KEY, generation_time, json_value=True)
    if is_base:
        set_config(MLBF_BASE_ID_CONFIG_KEY, generation_time, json_value=True)
