import json
import os

from django.core.management.base import BaseCommand
from django.conf import settings

import olympia.core.logger
from olympia.blocklist.mlbf import MLBF


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = 'Validates a given MLBF directory'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('storage_id', help='The storage ID of the MLBF', metavar=('ID'))

    def load_json(self, json_path):
        with open(json_path, 'r') as json_file:
            return json.load(json_file)

    def handle(self, *args, **options):
        storage_id = options['storage_id']
        mlbf = MLBF.load_from_storage(storage_id)
        mlbf.validate()
