import logging
import os
import shutil

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class BaseDataCommand(BaseCommand):
    # Settings for django-dbbackup
    data_backup_dirname = os.path.abspath(os.path.join(settings.ROOT, 'backups'))
    data_backup_init = '_init'
    data_backup_db_filename = 'db.sql'
    data_backup_storage_filename = 'storage.tar'

    call_command = call_command
    logger = logging

    def backup_dir_path(self, name):
        return os.path.abspath(os.path.join(self.data_backup_dirname, name))

    def backup_db_path(self, name):
        return os.path.abspath(
            os.path.join(self.backup_dir_path(name), self.data_backup_db_filename)
        )

    def backup_storage_path(self, name):
        return os.path.abspath(
            os.path.join(self.backup_dir_path(name), self.data_backup_storage_filename)
        )

    def clean_dir(self, name: str) -> None:
        path = self.backup_dir_path(name)
        logging.info(f'Clearing {path}')
        shutil.rmtree(path, ignore_errors=True)

    def make_dir(self, name: str, force: bool = False) -> None:
        path = self.backup_dir_path(name)
        path_exists = os.path.exists(path)

        if path_exists and not force:
            raise CommandError(
                f'path {path} already exists.' 'Use --force to overwrite.'
            )

        self.clean_dir(name)
        os.makedirs(path, exist_ok=True)
