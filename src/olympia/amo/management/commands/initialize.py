import logging

from django.conf import settings
from django.core.management import call_command

from olympia.users.models import UserProfile

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
        try:
            return UserProfile.objects.filter(email=settings.LOCAL_ADMIN_EMAIL).exists()
        except Exception as e:
            logging.error(f'Error checking if local admin exists: {e}')
            return False

    def handle(self, *args, **options):
        """
        Create the database.
        """
        logging.info(f'options: {options}')
        # We need to support skipping loading/seeding when desired.
        # Like in CI environments where you don't want to load data every time.
        if settings.DATA_BACKUP_SKIP:
            logging.info(
                'Skipping seeding and loading data because DATA_BACKUP_SKIP is set'
            )
            return

        # If DB empty or we are explicitly cleaning, then bail with data_seed.
        if options.get('clean') or not self.local_admin_exists():
            call_command('data_seed')
            return

        load = options.get('load')
        # We always migrate the DB.
        logging.info('Migrating...')
        call_command('migrate', '--noinput')

        # If we specify a specifi backup, simply load that.
        if load:
            call_command('data_load', '--name', load)
        # We should reindex even if no data is loaded/modified
        # because we might have a fresh instance of elasticsearch
        else:
            call_command(
                'reindex', '--wipe', '--force', '--noinput', '--skip-if-exists'
            )
