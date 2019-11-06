# -*- coding: utf-8 -*-
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import MySQLdb as mysql


class Command(BaseCommand):
    """Based on django_extension's reset_db command but simplifed and with
    support for all character sets defined in settings."""

    help = 'Creates the database for this project.'

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        parser.add_argument(
            '--force', action='store_true', help='Drops any existing database first.'
        )

    def handle(self, *args, **options):
        """
        Create the database.
        """
        db_info = settings.DATABASES.get('default')

        engine = db_info.get('ENGINE').split('.')[-1]
        if engine != 'mysql':
            raise CommandError('create_db only supports mysql databases')

        database_name = db_info.get('NAME')
        kwargs = {
            'user': db_info.get('USER'),
            'passwd': db_info.get('PASSWORD'),
            'host': db_info.get('HOST'),
        }
        if db_info.get('PORT'):
            kwargs['port'] = int(db_info.get('PORT'))
        connection = mysql.connect(**kwargs)

        if options.get('force'):
            drop_query = 'DROP DATABASE IF EXISTS `%s`' % database_name
        else:
            drop_query = None

        character_set = db_info.get('OPTIONS').get('charset', 'utf8mb4')
        create_query = 'CREATE DATABASE `%s` CHARACTER SET %s' % (
            database_name,
            character_set,
        )
        if drop_query:
            logging.info('Executing... "' + drop_query + '"')
            connection.query(drop_query)
        logging.info('Executing... "' + create_query + '"')
        connection.query(create_query)

        logging.info('Reset successful.')
