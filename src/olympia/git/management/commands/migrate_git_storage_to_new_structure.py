import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from olympia.files.utils import id_to_path


class Command(BaseCommand):
    help = 'Migrate git-storage to new directory structure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dont-migrate',
            action='store_true',
            help=('Only create the new directory structure, do not migrate anything.'),
        )
        parser.add_argument(
            '--dont-rename-root',
            action='store_true',
            help=('Migrate, but do not rename root directory at the end.'),
        )
        parser.add_argument(
            '--fake',
            action='store_true',
            help=('Fake all migration/rename operations.'),
        )

    def get_new_temporary_file_storage_path(self):
        """Temporary name for the new storage path.

        Once everything is migrated the old directory will be removed and we'll
        rename this one, removing the 'new-' prefix."""
        return os.path.join(settings.STORAGE_ROOT, 'new-git-storage')

    def get_old_temporary_file_storage_path(self):
        """Temporary name for the old storage path.

        Used at the very end, once we've migrated everything and we're about to
        rename the storage path."""
        return os.path.join(settings.STORAGE_ROOT, 'old-git-storage')

    def handle(self, *args, **options):
        self.verbosity = int(options.get('verbosity', 0))
        self.fake = bool(options.get('fake'))
        self.print_prefix = '[fake] ' if self.fake else ''
        old_git_file_storage_path = self.get_old_temporary_file_storage_path()
        if os.path.exists(old_git_file_storage_path):
            raise CommandError(f'{old_git_file_storage_path} should not exist')
        self.create_new_directory_structure()
        if options.get('dont_migrate'):
            if self.verbosity:
                self.stdout.write('Not migrating per --dont-migrate parameter.\n')
            return
        self.migrate()
        if options.get('dont_rename_root'):
            if self.verbosity:
                self.stdout.write(
                    'Not renaming top directory per --dont-rename-root parameter.\n'
                )
            return
        self.rename_top_directory()

    def get_new_path(self, addon_id):
        return os.path.join(
            self.get_new_temporary_file_storage_path(), id_to_path(addon_id, depth=3)
        )

    def create_new_directory_structure(self):
        new_file_storage_path = self.get_new_temporary_file_storage_path()
        for x in range(0, 10):
            for y in range(0, 10):
                # We only have a single add-on with an id < 3 digits, and its
                # id is 60, let's add it manually.
                zrange = list(range(0, 10))
                if x == 0 and y == 6:
                    zrange.append(60)
                for z in zrange:
                    path = os.path.join(
                        new_file_storage_path,
                        f'{x}',
                        f'{y}{x}',
                        f'{z}{y}{x}' if z < 10 else f'{z}',
                    )
                    self.stdout.write(f'Creating {path}\n')
                    os.makedirs(path, exist_ok=True)

    def migrate(self):
        n = 0
        for x in range(0, 10):
            for y in range(0, 10):
                path = os.path.join(
                    settings.GIT_FILE_STORAGE_PATH,
                    f'{x}',
                    f'{y}{x}',
                )
                try:
                    entries = os.scandir(path)
                except FileNotFoundError as exception:
                    self.stdout.write(f'{exception}\n')
                    continue
                for entry in entries:
                    n += 1
                    if self.verbosity >= 2 or (self.verbosity == 1 and n % 100 == 0):
                        self.stdout.write(
                            f'{self.print_prefix}Migrating {entry.name} (n={n:,})\n'
                        )
                    if not self.fake:
                        # If this fails, we want to abort and fail loudly: it
                        # could mean we're trying to migrate something that
                        # already has an extraction on the new directory, which
                        # shouldn't happen!
                        os.rename(entry.path, self.get_new_path(entry.name))

    def rename_top_directory(self):
        new_file_storage_path = self.get_new_temporary_file_storage_path()
        old_file_storage_path = self.get_old_temporary_file_storage_path()
        self.stdout.write(
            f'{self.print_prefix}Renaming old top directory '
            f'({settings.GIT_FILE_STORAGE_PATH} -> {old_file_storage_path})'
            '\n'
        )
        if not self.fake:
            os.rename(settings.GIT_FILE_STORAGE_PATH, old_file_storage_path)
        self.stdout.write(
            f'{self.print_prefix}Renaming new top directory '
            f'({new_file_storage_path} -> {settings.GIT_FILE_STORAGE_PATH})'
            '\n'
        )
        if not self.fake:
            os.rename(new_file_storage_path, settings.GIT_FILE_STORAGE_PATH)
