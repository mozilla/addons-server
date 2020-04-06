import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage

import olympia.core.logger

from olympia.blocklist.mlbf import generate_mlbf


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

    def save_blocklist(self, stats, mlbf, id_):
        out_file = os.path.join(settings.MLBF_STORAGE_PATH, f'{id_}.filter')

        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        with default_storage.open(out_file, 'wb') as mlbf_file:
            log.info("Writing to file {}".format(out_file))
            mlbf.tofile(mlbf_file)
        stats['mlbf_filesize'] = os.stat(out_file).st_size

    def handle(self, *args, **options):
        log.debug('Exporting blocklist to file')
        stats = {}
        generate_kw = {}
        if options.get('block_guids_input'):
            generate_kw['blocked'] = (
                self.load_json(options.get('block_guids_input')))
        if options.get('addon_guids_input'):
            generate_kw['not_blocked'] = (
                self.load_json(options.get('addon_guids_input')))

        mlbf = generate_mlbf(stats, **generate_kw)
        self.save_blocklist(
            stats,
            mlbf,
            options.get('id'))
        print(stats)
