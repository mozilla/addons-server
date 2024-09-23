import logging
import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Dump data with a specified name'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default=datetime.now().strftime(
                '%Y%m%d%H%M%S'
            ),  # Default to current timestamp
            help='Name of the data dump',
        )
        parser.add_argument(
            '--force', action='store_true', help='Force overwrite of existing dump'
        )

    def handle(self, *args, **options):
        name = options.get('name')
        force = options.get('force')

        dump_path = os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, name))

        logging.info(f'Dumping data to {dump_path}')

        if os.path.exists(dump_path):
            if force:
                shutil.rmtree(dump_path)
            else:
                raise CommandError(
                    f'Dump path {dump_path} already exists.'
                    'Use --force to overwrite or --init to reseed the initial data.'
                )

        os.makedirs(dump_path, exist_ok=True)

        data_file_path = os.path.join(dump_path, 'data.json')
        call_command(
            'dumpdata',
            format='json',
            indent=2,
            output=data_file_path,
            all=True,
            natural_foreign=True,
            natural_primary=True,
            exclude=[
                'contenttypes.contenttype',
                'auth.permission',
                'sessions.session',
            ]
        )

        storage_from = settings.STORAGE_ROOT
        storage_to = os.path.join(dump_path, 'storage')
        shutil.copytree(storage_from, storage_to)
