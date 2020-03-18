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
from olympia.users.utils import get_task_user

from .models import Block, BLSubmission, KintoImport
from .utils import block_activity_log_save


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')


@task
@use_primary_db
def process_blsubmission(multi_block_submit_id, **kw):
    obj = BLSubmission.objects.get(pk=multi_block_submit_id)
    if obj.action == BLSubmission.ACTION_ADDCHANGE:
        # create the blocks from the guids in the multi_block
        obj.save_to_block_objects()
    elif obj.action == BLSubmission.ACTION_DELETE:
        # delete the blocks
        obj.delete_block_objects()


@task
@use_primary_db
@transaction.atomic
def import_block_from_blocklist(record):
    kinto_id = record.get('id')
    using_db = 'replica' if 'replica' in settings.DATABASES else 'default'
    log.debug('Processing block id: [%s]', kinto_id)
    kinto = KintoImport.objects.create(kinto_id=kinto_id, record=record)

    guid = record.get('guid')
    if not guid:
        kinto.update(outcome=KintoImport.OUTCOME_MISSINGGUID)
        log.error('Kinto %s: GUID is falsey, skipping.', kinto_id)
        return
    version_range = record.get('versionRange', [{}])[0]
    target_application = version_range.get('targetApplication') or [{}]
    target_GUID = target_application[0].get('guid')
    if target_GUID and target_GUID != amo.FIREFOX.guid:
        kinto.update(outcome=KintoImport.OUTCOME_NOTFIREFOX)
        log.error(
            'Kinto %s: targetApplication (%s) is not Firefox, skipping.',
            kinto_id, target_GUID)
        return
    block_kw = {
        'min_version': version_range.get('minVersion', '0'),
        'max_version': version_range.get('maxVersion', '*'),
        'url': record.get('details', {}).get('bug'),
        'reason': record.get('details', {}).get('why', ''),
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
        log.debug(
            'Kinto %s: Attempting to create Blocks for addons matching [%s]',
            kinto_id, guid_regexp)
        addons_qs = Addon.unfiltered.using(using_db).filter(
            guid__regex=guid_regexp)
        # We need to mark this id in a way so we know its from a
        # regex guid - otherwise we might accidentally overwrite it.
        block_kw['kinto_id'] = '*' + block_kw['kinto_id']
        regex = True
    else:
        log.debug(
            'Kinto %s: Attempting to create a Block for guid [%s]',
            kinto_id, guid)
        addons_qs = Addon.unfiltered.using(using_db).filter(guid=guid)
        regex = False
    for addon in addons_qs:
        (block, created) = Block.objects.update_or_create(
            guid=addon.guid,
            defaults=dict(guid=addon.guid, **block_kw))
        block_activity_log_save(block, change=not created)
        if created:
            log.debug('Kinto %s: Added Block for [%s]', kinto_id, block.guid)
            block.update(modified=modified_date)
        else:
            log.debug('Kinto %s: Updated Block for [%s]', kinto_id, block.guid)
    if addons_qs:
        kinto.update(outcome=(KintoImport.OUTCOME_REGEXBLOCKS if regex else
                              KintoImport.OUTCOME_BLOCK))
    else:
        kinto.update(outcome=KintoImport.OUTCOME_NOMATCH)
        log.debug(
            'Kinto %s: No addon found', kinto_id)
