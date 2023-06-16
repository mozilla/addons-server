from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.blocklist.models import Block, BlockVersion
from olympia.files.models import File


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = 'Migration to create BlockVersion instances for every Block'

    def handle(self, *args, **options):
        count = 0
        for block in Block.objects.all().iterator(1000):
            versions_qs = (
                File.objects.filter(version__addon__addonguid__guid=block.guid)
                .exclude(version__blockversion__id__isnull=False)
                .values_list('version__version', 'version_id')
            )
            block_versions = [
                BlockVersion(version_id=version_id, block=block)
                for version_str, version_id in versions_qs
                if block.min_version <= version_str and block.max_version >= version_str
            ]
            BlockVersion.objects.bulk_create(block_versions)
            count += 1
            if (count % 1000) == 0:
                log.info('Progress: %s Blocks processed so far' % count)

        log.info('Finished: %s Blocks processed' % count)
