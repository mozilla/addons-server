from django.conf import settings
from django.core.management import call_command

from .. import BaseDataCommand


class Command(BaseDataCommand):
    help = (
        'Reset and seed the database with initial data, '
        'generated add-ons, and data from AMO production.'
    )

    def handle(self, *args, **options):
        num_addons = 10
        num_themes = 5

        # Delete any existing data_seed backup
        self.clean_dir(self.data_backup_init)

        self.logger.info('Resetting database...')
        call_command('reset_db', '--no-utf8', '--noinput')
        # Delete any local storage files
        # This should happen after we reset the database to ensure any records
        # relying on storage are deleted.
        self.clean_storage()
        # Migrate the database
        call_command('migrate', '--noinput')

        self.logger.info('Loading initial data...')
        call_command('loaddata', 'initial.json')
        call_command('import_prod_versions')
        call_command(
            'createsuperuser',
            '--no-input',
            '--username',
            settings.LOCAL_ADMIN_USERNAME,
            '--email',
            settings.LOCAL_ADMIN_EMAIL,
        )
        call_command('loaddata', 'zadmin/users')

        self.logger.info('Generating add-ons...')
        call_command('generate_addons', '--app', 'firefox', num_addons)
        call_command('generate_addons', '--app', 'android', num_addons)
        call_command('generate_themes', num_themes)

        call_command('generate_default_addons_for_frontend')

        call_command('data_dump', '--name', self.data_backup_init)
        call_command('data_load', '--name', self.data_backup_init)
