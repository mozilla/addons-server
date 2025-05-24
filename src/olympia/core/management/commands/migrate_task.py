import random
from django.db.migrations.migration import Migration
import olympia.core.logger
from olympia.core.db.migrations import (
    MigrationTask,
)
from olympia.core.management.commands import BaseMigrationCommand


class Command(BaseMigrationCommand):
    help = 'Migrate tasks'
    log = olympia.core.logger.getLogger('z.core')

    def extend_arguments(self, parser):
        pass

    def get_operation(self, migration: Migration, **options):
        from django.apps import apps
        app = apps.get_app_config(migration.app_label)
        module_path = app.module.__name__
        return MigrationTask(f'{module_path}.migrations.{migration.name}.migration_task')

    def get_name(self, *args, **options):
        return str(random.randint(1000, 9999))
