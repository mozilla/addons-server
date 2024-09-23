import logging
import os
import shutil

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed the _init data dir with fresh data from the database'

    def handle(self, *args, **options):
        init_name = settings.DATA_BACKUP_INIT
        init_path = os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, init_name))
        logging.info(f'Clearing {init_path}')
        shutil.rmtree(init_path, ignore_errors=True)

        logging.info('Resetting database...')
        call_command('flush', '--noinput')
        call_command('migrate', '--noinput')
        # reindex --wipe will force the ES mapping to be re-installed. Useful to
        # make sure the mapping is correct before adding a bunch of add-ons.
        call_command('reindex', '--wipe', '--force', '--noinput')

        logging.info('Loading initial data...')
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

        logging.info('Generating add-ons...')
        call_command('generate_addons', '--app', 'firefox', 10)
        call_command('generate_addons', '--app', 'android', 10)
        call_command('generate_themes', 5)
        # These add-ons are specifically useful for the addons-frontend
        # homepage. You may have to re-run this, in case the data there
        # changes.
        call_command('generate_default_addons_for_frontend')
        logging.info(f'Dumping data to {init_path}')
        call_command('dump_data', '--name', init_name)
