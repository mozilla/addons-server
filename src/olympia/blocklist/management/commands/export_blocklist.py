import json

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.blocklist.mlbf import MLBF, MLBFDataType


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = 'Export AMO blocklist to filter cascade blob'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('id', help='CT baseline identifier', metavar=('ID'))
        parser.add_argument(
            '--block-type',
            help='The block type to export',
            default=MLBFDataType.BLOCKED.name,
            choices=[data_type.name for data_type in MLBFDataType],
        )
        parser.add_argument(
            '--addon-guids-input',
            help='Path to json file with [[guid, version],...] data for all '
            'addons. If not provided will be generated from '
            'Addons&Versions in the database',
            default=None,
        )
        parser.add_argument(
            '--block-guids-input',
            help='Path to json file with [[guid, version],...] data for '
            'Blocks.  If not provided will be generated from Blocks in '
            'the database',
            default=None,
        )

    def load_json(self, json_path):
        with open(json_path) as json_file:
            data = json.load(json_file)
        return [tuple(record) for record in data]

    def handle(self, *args, **options):
        log.debug('Exporting blocklist to file')
        data_type = MLBFDataType[options.get('block_type')]
        mlbf = MLBF.generate_from_db(options.get('id'))

        if options.get('block_guids_input'):
            mlbf.data.blocked_items = list(
                MLBF.hash_filter_inputs(
                    self.load_json(options.get('block_guids_input'))
                )
            )
        if options.get('addon_guids_input'):
            mlbf.data.not_blocked_items = list(
                MLBF.hash_filter_inputs(
                    self.load_json(options.get('addon_guids_input'))
                )
            )

        mlbf.generate_and_write_filter(data_type)
