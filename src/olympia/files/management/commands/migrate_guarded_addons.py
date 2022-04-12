import os
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.guarded_addons_path = os.path.join(settings.STORAGE_ROOT, 'guarded-addons')
        self.migrate()

    def migrate(self):
        # Note: we handle empty directories, but for ETA to be reliable, it's
        # best to remove them first by running find . -type d -empty -delete.
        total_entries = os.stat(self.guarded_addons_path).st_nlink - 1
        entries_migrated = 0
        entries = os.scandir(self.guarded_addons_path)
        for addon in entries:
            if not addon.name.startswith('.'):
                start_time = datetime.now()
                self.migrate_addon(addon)
                end_time = datetime.now()
                # Since we use the add-ons and not the files to compute the ETA
                # it's never going to be 100% accurate, but it should be good
                # enough.
                entries_migrated += 1
                elapsed = end_time - start_time
                if entries_migrated == 1 or entries_migrated % 1000 == 0:
                    eta = timedelta(
                        seconds=int(elapsed.total_seconds())
                        * (total_entries - entries_migrated)
                    )
                    print(f'Migrated {entries_migrated}/{total_entries}, ETA {eta}')

    def migrate_addon(self, addon):
        new_addon_path = os.path.join(settings.ADDONS_PATH, addon.name)
        os.makedirs(new_addon_path, exist_ok=True)
        files = os.scandir(addon.path)
        for file in files:
            self.migrate_file(addon, file)
        return

    def migrate_file(self, addon, file):
        old_path = file.path
        new_path = os.path.join(settings.ADDONS_PATH, addon.name, file.name)
        try:
            os.link(old_path, new_path)
        except FileExistsError:
            # This makes the migration re-runnable, at the expense of the ETA
            # being less accurate for the initial portion we already migrated
            # during a previous pass.
            print(f'Ignoring already existing {old_path}')
