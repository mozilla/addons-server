import requests

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.blocklist.models import KintoImport
from olympia.blocklist.tasks import (
    delete_imported_block_from_blocklist, import_block_from_blocklist)


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Populate AMO blocklist by importing v2 JSON blocklist from kinto')

    KINTO_JSON_BLOCKLIST_URL = 'https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons/records'  # noqa

    def handle(self, *args, **options):
        log.debug(
            'Downloading blocklist from %s', self.KINTO_JSON_BLOCKLIST_URL)
        response = requests.get(self.KINTO_JSON_BLOCKLIST_URL)

        data = response.json()['data']
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
            '%s new, %s modified, % deleted records from blocklist to process',
            len(new_records), len(modified_records), len(deleted_record_ids))
        for record in new_records + modified_records:
            import_block_from_blocklist.delay(record)
        if deleted_record_ids:
            log.debug(
                'Deleting Blocks that have been removed from v2 blocklist')
            for kinto_id in deleted_record_ids:
                delete_imported_block_from_blocklist.delay(kinto_id)
