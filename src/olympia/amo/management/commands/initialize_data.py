import logging
import os
import random
import time
from functools import wraps

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

import MySQLdb as mysql

from olympia.search.utils import get_es


def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        raise
                    else:
                        sleep = backoff_in_seconds * 2**x + random.uniform(0, 1)
                        logging.warning(
                            f'{wrapper.__name__} failed. '
                            f'Retrying in {sleep:.2f} seconds... Error: {str(e)}'
                        )
                        time.sleep(sleep)
                        x += 1

        return wrapper

    return decorator


class Command(BaseCommand):
    """
    Creates the database for this project.

    This command is idempotent and will not re-create the database if it already exists.
    It will also not re-seed the database or reindex the data
    if the database already exists.
    """

    help = 'Creates, seeds, and indexes the database for this project.'
    connection = None
    db_info = None
    db_exists = False
    num_addons = 10
    num_themes = num_addons

    def __init__(self, *args, **options):
        super().__init__(*args, **options)

        self.db_info = settings.DATABASES.get('default')
        self.connection = self.connect_to_db()
        self.db_exists = self.check_db_exists()

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--force-db', action='store_true', help='Force creating the database'
        )
        parser.add_argument(
            '--skip-seed',
            action='store_true',
            help='Skip seeding the database with addons',
        )
        parser.add_argument(
            '--skip-index', action='store_true', help='Skip indexing the database'
        )

    @retry_with_backoff(retries=3, backoff_in_seconds=1)
    def connect_to_db(self):
        engine = self.db_info.get('ENGINE').split('.')[-1]
        if engine != 'mysql':
            raise CommandError('create_db only supports mysql databases')

        kwargs = {
            'user': self.db_info.get('USER'),
            'passwd': self.db_info.get('PASSWORD'),
            'host': self.db_info.get('HOST'),
        }
        if self.db_info.get('PORT'):
            kwargs['port'] = int(self.db_info.get('PORT'))

        logging.info('connecting to db')
        return mysql.connect(**kwargs)

    @retry_with_backoff(retries=3, backoff_in_seconds=1)
    def check_db_exists(self):
        try:
            self.connection.select_db(self.db_info.get('NAME'))
            return True
        except mysql.Error as exc:
            logging.info(exc)
            return False

    def create_db(self):
        logging.info('Cleaning up directories linked to database records...')
        root = os.path.join('/', 'data', 'olympia')
        clean_dirs = (
            os.path.join(root, 'user-media'),
            os.path.join(root, 'tmp'),
        )

        for dir in clean_dirs:
            if os.path.exists(dir):
                logging.info(f'Cleaning up {dir}...')
                os.rmdir(dir)

        database_name = self.db_info.get('NAME')
        character_set = self.db_info.get('OPTIONS').get('charset', 'utf8mb4')

        if self.db_exists:
            drop_query = f'DROP DATABASE `{database_name}`'
            logging.info('Executing... "' + drop_query + '"')
            self.connection.query(drop_query)

        create_query = (
            f'CREATE DATABASE `{database_name}` CHARACTER SET {character_set}'
        )
        logging.info('Executing... "' + create_query + '"')
        self.connection.query(create_query)

    def seed_db(self):
        logging.info('Creating seed data...')
        # reindex --wipe will force the ES mapping to be re-installed. Useful to
        # make sure the mapping is correct before adding a bunch of add-ons.
        call_command('reindex', '--wipe', '--force', '--noinput')
        call_command('generate_addons', '--app', 'firefox', self.num_addons)
        call_command('generate_addons', '--app', 'android', self.num_addons)
        call_command('generate_themes', self.num_themes)
        # These add-ons are specifically useful for the addons-frontend
        # homepage. You may have to re-run this, in case the data there
        # changes.
        call_command('generate_default_addons_for_frontend')

    def load_initial_data(self):
        logging.info('Loading initial data...')
        call_command('loaddata', 'initial.json')
        call_command('import_prod_versions')
        call_command(
            'createsuperuser',
            '--no-input',
            '--username',
            'local_admin',
            '--email',
            'local_admin@mozilla.com',
        )
        call_command('loaddata', 'zadmin/users')

    def handle(self, *args, **options):
        """
        Create the database.
        """
        force_db = options.get('force_db')
        skip_seed = options.get('skip_seed')
        skip_index = options.get('skip_index')

        logging.info(f'options: {options}')

        # Initialize ES inside the handle method
        ES = get_es()

        # Step 1: Ensure the database exists
        # is migrated and contains initial data if creating.
        create_new_db = force_db or not self.db_exists

        # only create the db if we want to or need to
        self.create_db() if create_new_db else logging.info('Database already exists.')

        # Migrate database even if not creating anew.
        logging.info('Migrating...')
        call_command('migrate', '--noinput')

        # Load initial data after migrations
        self.load_initial_data() if create_new_db else logging.info(
            'Skipping load initial data.'
        )

        # Step 2: Seed the db if it is a fresh database or we have opted in to seeding.
        seed_db = create_new_db and not skip_seed

        self.seed_db() if seed_db else logging.info('Skipping seeding the database.')

        # Step 3: Index the db unless we opt out of indexing.
        alias = settings.ES_INDEXES.get('default', None)
        index_exists = ES.indices.exists(index=alias)

        will_index_db = (seed_db or not index_exists) and not skip_index

        if will_index_db:
            call_command('reindex', '--noinput', '--force')
        else:
            logging.info('Skipping indexing the database.')
