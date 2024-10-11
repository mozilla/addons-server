import logging

from django.conf import settings
from django.core.management import call_command

from .. import BaseDataCommand


class Command(BaseDataCommand):
    """
    Ensures the database has the correct state.
    """

    help = 'Creates, seeds, and indexes the database.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--clean', action='store_true', help='Reset the database with fresh data'
        )
        parser.add_argument(
            '--load',
            type=str,
            help='Optionally load data from a backup.',
        )

    def local_admin_exists(self):
        from olympia.users.models import UserProfile

        return UserProfile.objects.filter(email=settings.LOCAL_ADMIN_EMAIL).exists()

    def handle(self, *args, **options):
        """
        Create the database.
        """
        # We need to support skipping loading/seeding when desired.
        # Like in CI environments where you don't want to load data every time.
        if settings.DATA_BACKUP_SKIP:
            logging.info(
                'Skipping seeding and loading data because DATA_BACKUP_SKIP is set'
            )
            return

        clean = options.get('clean')
        load = options.get('load')
        logging.info(f'options: {options}')

        # We always migrate the DB.
        logging.info('Migrating...')
        call_command('migrate', '--noinput')

        # If we specify a specifi backup, simply load that.
        if load:
            call_command('data_load', '--name', load)
        # If DB empty or we are explicitly cleaning, then reseed.
        elif clean or not self.local_admin_exists():
            call_command('data_seed')
        # We should reindex even if no data is loaded/modified
        # because we might have a fresh instance of elasticsearch
        else:
            call_command('reindex', '--wipe', '--force', '--noinput')
