import os
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.files.models import File
from olympia.files.utils import id_to_path


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.migrate()

    def print_eta(self, *, elapsed, processed_count, remaining_count):
        # total_seconds() keeps microseconds - it should often be 0.xxxxxx in
        # our case. We use the full precision for computing the ETA, but round
        # to the second when displaying.
        total_seconds = elapsed.total_seconds()
        eta = (
            timedelta(seconds=int(total_seconds / processed_count * remaining_count))
            if processed_count
            else 'Unknown'
        )
        self.stdout.write(f'ETA {eta} ; Remaining entries {remaining_count}\n')

    def migrate(self):
        # Number of entries to migrate is number of links to the directory
        # minus `.`, the parent dir and `temp/` which we're not touching.
        entries_total = os.stat(settings.ADDONS_PATH).st_nlink - 3
        processed_count = 0
        migrated_count = 0
        entries = os.scandir(settings.ADDONS_PATH)
        start_time = datetime.now()
        for entry in entries:
            if not entry.name.isdigit():
                entries_total -= 1
                self.stderr.write(f'Ignoring non-addon entry {entry.name}')
                continue
            result = self.migrate_directory_contents(entry.name)
            migrated_count += result
            # Since we use the add-ons and not the files to compute the ETA
            # it's never going to be 100% accurate, but it should be good
            # enough.
            processed_count += 1
            if processed_count == 1 or processed_count % 1000 == 0:
                elapsed = datetime.now() - start_time
                self.print_eta(
                    elapsed=elapsed,
                    processed_count=processed_count,
                    remaining_count=entries_total - processed_count,
                )
        self.stdout.write(
            f'Processed {processed_count} entries (migrated {migrated_count}) '
            f'in {elapsed.total_seconds()} seconds.'
        )

    def migrate_directory_contents(self, dirname):
        old_dirpath = os.path.join(settings.ADDONS_PATH, dirname)
        new_dirpath = os.path.join(settings.ADDONS_PATH, id_to_path(dirname, breadth=2))
        os.makedirs(new_dirpath, exist_ok=True)
        migrrated_count_in_dir = 0
        for entry in os.scandir(old_dirpath):
            if entry.is_file() and entry.name.endswith(('.zip', '.xpi')):
                result = self.migrate_file(dirname, entry.name)
                if result:
                    migrrated_count_in_dir += 1
        return migrrated_count_in_dir

    def migrate_file(self, addon_pk, filename):
        filename_with_dirname = os.path.join(addon_pk, filename)
        old_path = os.path.join(settings.ADDONS_PATH, filename_with_dirname)
        try:
            instance = File.objects.select_related('version', 'version__addon').get(
                file=filename, version__addon=addon_pk
            )
        except File.DoesNotExist:
            self.stderr.write(
                f'Ignoring likely obsolete or already migrated {filename_with_dirname}'
            )
            return False
        new_filename_with_dirnames = instance._meta.get_field('file').upload_to(
            instance, filename
        )
        new_path = os.path.join(settings.ADDONS_PATH, new_filename_with_dirnames)
        try:
            os.link(old_path, new_path)
        except FileExistsError:
            # If we're here, it means the file has likely already been migrated
            # on the filesystem but the database hasn't been updated yet (maybe
            # we stopped the script and re-triggered it).
            self.stderr.write(f'Ignoring already migrated {filename_with_dirname}')
        instance.update(file=new_filename_with_dirnames)
        return True
