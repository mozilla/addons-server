import re
import time
from datetime import datetime

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.users.utils import get_task_user

from .models import Block, MultiBlockSubmit
from .utils import block_activity_log_save


log = olympia.core.logger.getLogger('z.amo.blocklist')

bracket_open_regex = re.compile(r'(?<!\\){')
bracket_close_regex = re.compile(r'(?<!\\)}')


@task
@use_primary_db
def create_blocks_from_multi_block(multi_block_submit_id, **kw):
    obj = MultiBlockSubmit.objects.get(pk=multi_block_submit_id)
    # create the blocks from the guids in the multi_block
    obj.save_to_blocks()


@task
@use_primary_db
def import_block_from_blocklist(record):
    log.debug('Processing block id: [%s]', record.get('id'))
    guid = record.get('guid')
    if not guid:
        log.error('GUID is falsey, skipping.')
        return
    version_range = record.get('versionRange', [{}])[0]
    target_application = version_range.get('targetApplication') or [{}]
    target_GUID = target_application[0].get('guid')
    if target_GUID and target_GUID != amo.FIREFOX.guid:
        log.error(
            'targetApplication (%s) is not Firefox, skipping.',
            target_GUID)
        return
    block_kw = {
        'min_version': version_range.get('minVersion', '0'),
        'max_version': version_range.get('maxVersion', '*'),
        'url': record.get('details', {}).get('bug'),
        'reason': record.get('details', {}).get('why', ''),
        'kinto_id': record.get('id'),
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
            'Attempting to create Blocks for addons matching [%s]',
            guid_regexp)
        addons_qs = Addon.unfiltered.filter(guid__regex=guid_regexp)
        # We need to mark this id in a way so we know its from a
        # regex guid - otherwise we might accidentally overwrite it.
        block_kw['kinto_id'] = '*' + block_kw['kinto_id']
    else:
        log.debug('Attempting to create a Block for guid [%s]', guid)
        addons_qs = Addon.unfiltered.filter(guid=guid)
    for addon in addons_qs:
        (block, created) = Block.objects.update_or_create(
            guid=addon.guid,
            defaults=dict(guid=addon.guid, **block_kw))
        block_activity_log_save(block, change=not created)
        if created:
            log.debug('Added Block for [%s]', block.guid)
            block.update(modified=modified_date)
        else:
            log.debug('Updated Block for [%s]', block.guid)
    else:
        log.debug(
            'No addon found for block id: [%s]', record.get('id'))
