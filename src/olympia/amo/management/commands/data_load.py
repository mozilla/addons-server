import os

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError

from .. import BaseDataCommand


class Command(BaseDataCommand):
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
        db_path = self.backup_db_path(name)
        storage_path = self.backup_storage_path(name)

        if not os.path.exists(db_path):
            print('DB backup not found: {db_path}')
            raise CommandError(f'DB backup not found: {db_path}')

        call_command(
            'dbrestore',
            input_path=db_path,
            interactive=False,
            uncompress=True,
        )

        if not os.path.exists(storage_path):
            raise CommandError(f'Storage backup not found: {storage_path}')

        cache.clear()
        self.clean_storage()

        call_command(
            'mediarestore',
            input_path=storage_path,
            interactive=False,
            uncompress=True,
            replace=True,
        )

        # reindex --wipe will force the ES mapping to be re-installed.
        # After loading data from a backup, we should always reindex
        # to make sure the mapping is correct.
        call_command('reindex', '--wipe', '--force', '--noinput')
