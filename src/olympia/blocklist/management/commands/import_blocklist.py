import requests

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.blocklist.models import KintoImport
from olympia.blocklist.tasks import import_block_from_blocklist


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Populate AMO blocklist by importing v2 JSON blocklist from kinto')

    KINTO_JSON_BLOCKLIST_URL = 'https://firefox.settings.services.mozilla.com/v1/buckets/blocklists/collections/addons/records'  # noqa

    def handle(self, *args, **options):
        log.debug(
            'Downloading blocklist from %s', self.KINTO_JSON_BLOCKLIST_URL)
        response = requests.get(self.KINTO_JSON_BLOCKLIST_URL)

        # filter out the blocks we've already imported
        kinto_ids = [record['id'] for record in response.json()['data']]
        already_imported = list(KintoImport.objects.filter(
            kinto_id__in=kinto_ids).values_list('kinto_id', flat=True))
        records = [
            record for record in response.json()['data']
            if record['id'] not in already_imported]
        log.debug('%s records from blocklist to process', len(records))
        for record in records:
            import_block_from_blocklist.delay(record)
