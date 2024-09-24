from django.conf import settings

from ..base import BaseDataCommand


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
        self.call_command('flush', '--noinput')
        self.call_command('migrate', '--noinput')
        # reindex --wipe will force the ES mapping to be re-installed. Useful to
        # make sure the mapping is correct before adding a bunch of add-ons.
        self.call_command('reindex', '--wipe', '--force', '--noinput')

        self.logger.info('Loading initial data...')
        self.call_command('loaddata', 'initial.json')
        self.call_command('import_prod_versions')
        self.call_command(
            'createsuperuser',
            '--no-input',
            '--username',
            settings.LOCAL_ADMIN_USERNAME,
            '--email',
            settings.LOCAL_ADMIN_EMAIL,
        )
        self.call_command('loaddata', 'zadmin/users')

        self.logger.info('Generating add-ons...')
        self.call_command('generate_addons', '--app', 'firefox', num_addons)
        self.call_command('generate_addons', '--app', 'android', num_addons)
        self.call_command('generate_themes', num_themes)

        self.call_command('generate_default_addons_for_frontend')

        self.call_command('dump_data', '--name', self.data_backup_init)
