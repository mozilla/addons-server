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

        self.clean_dir(self.data_backup_init)

        self.logger.info('Resetting database...')
        call_command('flush', '--noinput')
        # reindex --wipe will force the ES mapping to be re-installed.
        call_command('reindex', '--wipe', '--force', '--noinput')
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
