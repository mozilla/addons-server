import re
import time
from datetime import datetime

from django.conf import settings
from django.db import transaction

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.files.models import File
from olympia.users.utils import get_task_user

from .models import Block, BlocklistSubmission, KintoImport
from .utils import block_activity_log_save, split_regex_to_list


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')


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
    using_db = 'replica' if 'replica' in settings.DATABASES else 'default'
    log.debug('Processing block id: [%s]', kinto_id)
    kinto_import = KintoImport(kinto_id=kinto_id, record=record)

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
            log.debug(
                'Kinto %s: Broke down regex into list; '
                'attempting to create Blocks for guids in %s',
                kinto_id, guids_list)
            addons_guids_qs = Addon.unfiltered.using(using_db).filter(
                guid__in=guids_list).values_list('guid', flat=True)
        else:
            log.debug(
                'Kinto %s: Unable to break down regex into list; '
                'attempting to create Blocks for guids matching [%s]',
                kinto_id, guid_regexp)
            addons_guids_qs = Addon.unfiltered.using(using_db).filter(
                guid__regex=guid_regexp).values_list('guid', flat=True)
        # We need to mark this id in a way so we know its from a
        # regex guid - otherwise we might accidentally overwrite it.
        block_kw['kinto_id'] = '*' + block_kw['kinto_id']
        regex = True
    else:
        log.debug(
            'Kinto %s: Attempting to create a Block for guid [%s]',
            kinto_id, guid)
        addons_guids_qs = Addon.unfiltered.using(using_db).filter(
            guid=guid).values_list('guid', flat=True)
        regex = False
    new_blocks = []
    for guid in addons_guids_qs:
        valid_files_qs = File.objects.filter(
            version__addon__guid=guid, is_signed=True, is_webextension=True)
        if not valid_files_qs.exists():
            log.debug(
                'Kinto %s: Skipped Block for [%s] because it has no signed '
                'webextension files', kinto_id, guid)
            continue
        (block, created) = Block.objects.update_or_create(
            guid=guid, defaults=dict(guid=guid, **block_kw))
        block_activity_log_save(block, change=not created)
        if created:
            log.debug('Kinto %s: Added Block for [%s]', kinto_id, guid)
            block.update(modified=modified_date)
        else:
            log.debug('Kinto %s: Updated Block for [%s]', kinto_id, guid)
        new_blocks.append(block)
    if new_blocks:
        kinto_import.outcome = (
            KintoImport.OUTCOME_REGEXBLOCKS if regex else
            KintoImport.OUTCOME_BLOCK
        )
    else:
        kinto_import.outcome = KintoImport.OUTCOME_NOMATCH
        log.debug('Kinto %s: No addon found', kinto_id)
    kinto_import.save()
