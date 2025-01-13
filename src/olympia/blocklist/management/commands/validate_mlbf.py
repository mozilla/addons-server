from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.blocklist.mlbf import MLBF


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = 'Validates a given MLBF directory'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('storage_id', help='The storage ID of the MLBF', metavar=('ID'))

    def handle(self, *args, **options):
        storage_id = options['storage_id']
        mlbf = MLBF.load_from_storage(storage_id)
        mlbf.validate()
