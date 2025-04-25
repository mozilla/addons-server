from functools import cached_property

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.migration import Migration
from django.db.migrations.operations.base import Operation
from django.db.migrations.writer import MigrationWriter

import olympia.core.logger


class BaseMigrationCommand(BaseCommand):
    log = olympia.core.logger.getLogger('z.core')

    def add_arguments(self, parser):
        parser.add_argument(
            'app_label',
            type=str,
            help='The app label of the migration',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dry run the migration',
        )
        self.extend_arguments(parser)

    @cached_property
    def graph(self) -> MigrationGraph:
        return MigrationLoader(connections['default'], ignore_no_migrations=True).graph

    def migration(self, name: str, app_label: str) -> Migration:
        return Migration(name, app_label)

    def writer(self, migration: Migration) -> MigrationWriter:
        return MigrationWriter(migration)

    def print(self, filename: str, output: str) -> None:
        self.stdout.write(f'{filename}: \n')
        self.stdout.write(output)

    def get_name(self, *args, **options) -> str:
        """
        Return the name of the migration excluding the migration number.
        """
        raise NotImplementedError

    def get_operation(self, *args, **options) -> Operation:
        """
        Return the operation to be performed in the migration.
        """
        raise NotImplementedError

    def extend_arguments(self, parser) -> None:
        """
        Extend the arguments of the command.
        """
        raise NotImplementedError

    def handle(self, *args, **options):
        app_label = options.get('app_label')
        dry_run = options.get('dry_run', False)
        name = self.get_name(*args, **options)

        leaf_nodes = self.graph.leaf_nodes(app_label)
        migration_number = 1

        if leaf_nodes and (node := leaf_nodes[-1]):
            migration_number = int(node[1].split('_', 1)[0]) + 1

        migration_name = f'{migration_number:04d}_{name}'

        migration = self.migration(migration_name, app_label)
        migration.dependencies = leaf_nodes
        migration.operations = [self.get_operation(*args, **options)]

        writer = self.writer(migration)
        filename = writer.path
        output = writer.as_string()

        if dry_run:
            self.print(filename, output)
            return output

        with open(filename, 'w') as f:
            f.write(output)
