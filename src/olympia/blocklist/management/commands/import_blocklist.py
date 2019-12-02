import re
import requests
from datetime import datetime

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.blocklist.models import Block
from olympia.blocklist.utils import block_activity_log_save
from olympia.users.utils import get_task_user


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Populate AMO blocklist by import v2 JSON blocklist from kinto.')

    KINTO_JSON_BLOCKLIST_URL = 'https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons/records'  # noqa
    bracket_open_regex = re.compile(r'(?<!\\){')
    bracket_close_regex = re.compile(r'(?<!\\)}')

    def handle(self, *args, **options):
        log.debug(
            'Downloading blocklist from %s', self.KINTO_JSON_BLOCKLIST_URL)
        response = requests.get(self.KINTO_JSON_BLOCKLIST_URL)
        for record in response.json()['data']:
            log.debug('Processing block id: [%s]', record.get('id'))
            guid = record.get('guid')
            if not guid:
                log.error('GUID is falsey, skipping.')
                continue
            version_range = record.get('versionRange', [{}])[0]
            target_application = version_range.get('targetApplication') or [{}]
            target_GUID = target_application[0].get('guid')
            if target_GUID and target_GUID != amo.FIREFOX.guid:
                log.error(f'targetApplication is not Firefox, skipping. {target_GUID}')
                continue
            block_kw = {
                'min_version': version_range.get('minVersion', '0'),
                'max_version': version_range.get('maxVersion', '*'),
                'url': record.get('details', {}).get('bug'),
                'reason': record.get('details', {}).get('why', ''),  # + who, name?
                'kinto_id': record.get('id'),
                'include_in_legacy': True,
                'updated_by': get_task_user(),
                'modified': record.get('last_modified', datetime.now()),
            }

            if guid.startswith('/'):
                # need to escape the {} brackets or mysql chokes.
                guid_regexp = self.bracket_open_regex.sub(r'\{', guid[1:-1])
                guid_regexp = self.bracket_close_regex.sub(r'\}', guid_regexp)
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
                else:
                    log.debug('Updated Block for [%s]', block.guid)
            else:
                log.debug(
                    'No addon found for block id: [%s]', record.get('id'))
