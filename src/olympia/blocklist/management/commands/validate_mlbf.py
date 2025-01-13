from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.blocklist.mlbf import MLBF


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = 'Validates a given MLBF directory'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            'storage_id', help='The storage ID of the MLBF', metavar=('ID')
        )
        parser.add_argument(
            '--fail-fast',
            action='store_true',
            help='Fail fast if an error is found',
            default=False,
        )

    def handle(self, *args, **options):
        storage_id = options['storage_id']
        fail_fast = options['fail_fast']
        log.info(f'Validating MLBF {storage_id} with fail_fast={fail_fast}')
        mlbf = MLBF.load_from_storage(storage_id, error_on_missing=True)
        mlbf.validate(fail_fast=fail_fast)
