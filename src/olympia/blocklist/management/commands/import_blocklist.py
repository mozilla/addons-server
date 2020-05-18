import requests

from django.conf import settings
from django.core.management.base import BaseCommand

from django_statsd.clients import statsd

import olympia.core.logger

from olympia.blocklist.models import KintoImport
from olympia.blocklist.tasks import (
    delete_imported_block_from_blocklist, import_block_from_blocklist)
from olympia.constants.blocklist import REMOTE_SETTINGS_COLLECTION_LEGACY


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = (
        'Populate AMO blocklist by importing legacy JSON blocklist from '
        'remote settings')

    def handle(self, *args, **options):
        LEGACY_BLOCKLIST_URL = (
            f'{settings.REMOTE_SETTINGS_API_URL}buckets/blocklists/'
            f'collections/{REMOTE_SETTINGS_COLLECTION_LEGACY}/records')
        log.debug('Downloading blocklist from %s', LEGACY_BLOCKLIST_URL)
        response = requests.get(LEGACY_BLOCKLIST_URL)

        data = response.json().get('data', [])
        kinto_ids = [record['id'] for record in data]
        # filter out the blocks we've already imported
        kinto_import_qs = KintoImport.objects.all().values_list(
            'kinto_id', 'timestamp', named=True)
        already_imported = {
            import_.kinto_id: import_.timestamp for import_ in kinto_import_qs}
        new_records = [
            record for record in data
            if record['id'] not in already_imported
        ]
        modified_records = [
            record for record in data
            if record['id'] in already_imported and
            record['last_modified'] != already_imported[record['id']]
        ]
        deleted_record_ids = [
            kinto_id for kinto_id in already_imported
            if kinto_id not in kinto_ids
        ]
        log.debug(
            '%s new, %s modified, %s deleted records from legacy blocklist to '
            'process',
            len(new_records), len(modified_records), len(deleted_record_ids))
        statsd.incr(
            'blocklist.import_blocklist.new_record_found',
            count=len(new_records))
        statsd.incr(
            'blocklist.import_blocklist.modified_record_found',
            count=len(modified_records))
        statsd.incr(
            'blocklist.import_blocklist.deleted_record_found',
            count=len(deleted_record_ids))
        for record in new_records + modified_records:
            import_block_from_blocklist.delay(record)
        if deleted_record_ids:
            log.debug(
                'Deleting Blocks that have been removed from legacy blocklist')
            for kinto_id in deleted_record_ids:
                delete_imported_block_from_blocklist.delay(kinto_id)
