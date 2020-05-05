import json

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.blocklist.mlbf import MLBF


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Export AMO blocklist to filter cascade blob')

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            'id',
            help="CT baseline identifier",
            metavar=('ID'))
        parser.add_argument(
            '--addon-guids-input',
            help='Path to json file with [[guid, version],...] data for all '
                 'addons. If not provided will be generated from '
                 'Addons&Versions in the database',
            default=None)
        parser.add_argument(
            '--block-guids-input',
            help='Path to json file with [[guid, version],...] data for '
                 'Blocks.  If not provided will be generated from Blocks in '
                 'the database',
            default=None)

    def load_json(self, json_path):
        with open(json_path) as json_file:
            data = json.load(json_file)
        return [tuple(record) for record in data]

    def handle(self, *args, **options):
        log.debug('Exporting blocklist to file')
        mlbf = MLBF(options.get('id'))

        if options.get('block_guids_input'):
            mlbf.blocked_json = MLBF.hash_filter_inputs(
                self.load_json(options.get('block_guids_input')))
        if options.get('addon_guids_input'):
            mlbf.not_blocked_json = MLBF.hash_filter_inputs(
                self.load_json(options.get('addon_guids_input')))

        mlbf.generate_and_write_mlbf()
