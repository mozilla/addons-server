import os
import shutil

from django.conf import settings
from django.core.management import call_command

from .. import BaseDataCommand


class Command(BaseDataCommand):
    help = (
        'Reset and seed the database with initial data, '
        'generated add-ons, and data from AMO production.'
    )

    def _clean_storage(self, root: str, dir_dict: dict[str, str | dict]) -> None:
        for key, value in dir_dict.items():
            curr_path = os.path.join(root, key)
            if isinstance(value, dict):
                self._clean_storage(curr_path, value)
            else:
                shutil.rmtree(curr_path, ignore_errors=True)
                os.makedirs(curr_path, exist_ok=True)

    def clean_storage(self):
        self.logger.info('Cleaning storage...')
        self._clean_storage(
            settings.STORAGE_ROOT,
            {
                'files': '',
                'shared_storage': {
                    'tmp': {
                        'addons': '',
                        'data': '',
                        'file_viewer': '',
                        'guarded-addons': '',
                        'icon': '',
                        'log': '',
                        'persona_header': '',
                        'preview': '',
                        'test': '',
                        'uploads': '',
                    },
                    'uploads': '',
                },
            },
        )

    def handle(self, *args, **options):
        num_addons = 10
        num_themes = 5

        self.clean_dir(self.data_backup_init)

        self.logger.info('Resetting database...')
        call_command('flush', '--noinput')
        self.clean_storage()
        # reindex --wipe will force the ES mapping to be re-installed.
        call_command('reindex', '--wipe', '--force', '--noinput')
        call_command('migrate', '--noinput')

        self.logger.info('Loading initial data...')
        call_command('loaddata', 'initial.json')
        call_command('import_prod_versions')
        call_command('import_licenses')
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
