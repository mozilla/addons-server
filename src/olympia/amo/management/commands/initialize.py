import logging

from django.conf import settings
from django.core.management import call_command

from olympia.users.models import UserProfile

from .. import BaseDataCommand


class Command(BaseDataCommand):
    """
    Ensures the database has the correct state.
    """

    # We don't want to run system checks here, because this command
    # can run before everything is ready.
    # we run them at the end of the command.
    requires_system_checks = []

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
        # Always ensure "olympia" database exists and is accessible.
        call_command('monitors', services=['olympia_database', 'elastic'])

        if (
            # If we are not skipping data seeding
            not settings.SKIP_DATA_SEED
            # and we are either explicitly cleaning or loading a fresh db
            and (options.get('clean') or not self.local_admin_exists())
        ):
            call_command('data_seed')
        # Otherwise, we're working with a pre-existing DB.
        else:
            load = options.get('load')
            # We always migrate the DB.
            logging.info('Migrating...')
            call_command('migrate', '--noinput')

            # If we specify a specific backup, simply load that.
            if load:
                call_command('data_load', '--name', load)
            # We should reindex even if no data is loaded/modified
            # because we might have a fresh instance of elasticsearch
            else:
                call_command(
                    'reindex', '--wipe', '--force', '--noinput', '--skip-if-exists'
                )

        # By now, we excpect the database to exist, and to be migrated
        # so our database tables should be accessible
        call_command('monitors', services=['database'])

        # Ensure that the storage directories exist.
        self.make_storage(clean=False)

        # Ensure any additional required dependencies are available before proceeding.
        call_command(
            'monitors',
            services=[
                'localdev_web',
                'localdev_static',
                'celery_worker',
                'rabbitmq',
                'signer',
            ],
            attempts=10,
        )

        # Finally, run the django checks to ensure everything is ok.
        call_command('check')
