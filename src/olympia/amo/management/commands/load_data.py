import logging
import os
import shutil

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Load data from a specified name'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Name of the data dump',
        )

    def handle(self, *args, **options):
        name = options.get('name')
        load_path = os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, name))

        logging.info(f'Loading data from {load_path}')

        if not os.path.exists(load_path):
            raise CommandError(f'Dump path {load_path} does not exist.')

        data_file_path = os.path.join(load_path, 'data.json')
        call_command('loaddata', data_file_path)

        storage_from = os.path.join(load_path, 'storage')
        storage_to = os.path.abspath(settings.STORAGE_ROOT)
        logging.info(f'Copying storage from {storage_from} to {storage_to}')
        shutil.copytree(storage_from, storage_to, dirs_exist_ok=True)
