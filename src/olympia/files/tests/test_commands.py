import io
import os
from datetime import timedelta
from unittest import mock

from freezegun import freeze_time

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.files.management.commands.migrate_guarded_addons import (
    Command as MigrateGuardedAddons,
    Entry,
)


class TestMigrateGuardedAddons(TestCase):
    def setUp(self):
        self.command = MigrateGuardedAddons()
        self.command.verbosity = 1
        self.command.stderr = io.StringIO()
        self.command.stdout = io.StringIO()

    def test_migrate_file(self):
        addon = Entry('foo', '/guarded-addons/foo')
        file_ = Entry('bar.xpi', '/guarded-addons/foo/bar.xpi')
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            self.command.migrate_file(addon, file_)
        expected_path = os.path.join(settings.ADDONS_PATH, addon.name, 'bar.xpi')
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((file_.path, expected_path),)

    def test_migrate_file_already_exists(self):
        addon = Entry('foo', '/guarded-addons/foo')
        file_ = Entry('bar.xpi', '/guarded-addons/foo/bar.xpi')
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            mocked_link.side_effect = FileExistsError
            self.command.migrate_file(addon, file_)
        expected_path = os.path.join(settings.ADDONS_PATH, addon.name, 'bar.xpi')
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((file_.path, expected_path),)
        self.command.stderr.seek(0)
        assert (
            self.command.stderr.read()
            == 'Ignoring already existing /guarded-addons/foo/bar.xpi'
        )

    def test_migrate_addon(self):
        self.command.guarded_addons_path = os.path.join(
            settings.STORAGE_ROOT, 'guarded-addons'
        )
        expected_elapsed = timedelta(seconds=42)
        addon = Entry('foo', os.path.join(self.command.guarded_addons_path, 'foo'))
        os.makedirs(addon.path)
        file_path = os.path.join(addon.path, 'bar.xpi')
        with open(file_path, 'w') as f:
            f.write('a')
        expected_file = Entry('bar.xpi', file_path)
        with freeze_time('2022-04-13 12:00') as frozen_time:
            with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
                migrate_file_mock.side_effect = lambda *args: frozen_time.tick(
                    delta=expected_elapsed
                )
                rval = self.command.migrate_addon(addon)
        assert migrate_file_mock.call_count == 1
        assert migrate_file_mock.call_args[0] == (addon, expected_file)
        assert rval == expected_elapsed

    def test_migrate_addon_empty_dir(self):
        self.command.guarded_addons_path = os.path.join(
            settings.STORAGE_ROOT, 'guarded-addons'
        )
        addon = Entry('foo', os.path.join(self.command.guarded_addons_path, 'foo'))
        os.makedirs(addon.path)
        with freeze_time('2022-04-13 12:00') as frozen_time:
            with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
                migrate_file_mock.side_effect = lambda *args: frozen_time.tick(
                    delta=timedelta(seconds=42)
                )
                rval = self.command.migrate_addon(addon)
        assert migrate_file_mock.call_count == 0
        # migrate_file() takes 42 seconds but was never called so elapsed time
        # should be 0.
        assert rval == timedelta(seconds=0)

    def test_print_eta(self):
        elapsed = timedelta(seconds=0, microseconds=191332)
        remaining_entries = 481516
        self.command.print_eta(elapsed=elapsed, remaining_entries=remaining_entries)
        self.command.stdout.seek(0)
        assert (
            self.command.stdout.read()
            == 'ETA 1 day, 1:35:29 ; Remaining entries 481516\n'
        )

    def test_print_eta_shorter(self):
        elapsed = timedelta(seconds=0, microseconds=566784)
        remaining_entries = 2342
        self.command.print_eta(elapsed=elapsed, remaining_entries=remaining_entries)
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:22:07 ; Remaining entries 2342\n'

    def test_print_eta_0_remaining(self):
        elapsed = timedelta(seconds=0, microseconds=123456)
        remaining_entries = 0
        self.command.print_eta(elapsed=elapsed, remaining_entries=remaining_entries)
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:00:00 ; Remaining entries 0\n'

    @mock.patch('olympia.files.management.commands.migrate_guarded_addons.os.scandir')
    def test_migrate(self, scandir_mock):
        guarded_addons_path = os.path.join(settings.STORAGE_ROOT, 'guarded-addons')
        # Return 2001 addon directories and a stray .whatever that should be ignored.
        scandir_mock.return_value = [
            mock.Mock(
                spec=os.DirEntry,
                _name=str(x),
                path=os.path.join(guarded_addons_path, str(x)),
            )
            for x in range(1, 2002)
        ] + [
            mock.Mock(
                spec=os.DirEntry,
                _name='.whatever',
                path=os.path.join(guarded_addons_path, '.whatever'),
            )
        ]
        for mocked in scandir_mock.return_value:
            mocked.name = (
                mocked._name
            )  # Ugly but `name` is a special attribute in mocks.
        with mock.patch.object(self.command, 'migrate_addon') as migrate_addon_mock:
            self.command.migrate()
        # We're mocking migrate_addon() so scandir() should have been called
        # only once.
        assert scandir_mock.call_count == 1
        assert scandir_mock.call_args == ((guarded_addons_path,),)
        assert migrate_addon_mock.call_count == 2001
        assert migrate_addon_mock.call_args_list[23] == (
            (Entry('24', os.path.join(guarded_addons_path, '24')),),
        )
        self.command.stdout.seek(0)
        # We should have printed the ETA 3 times.
        assert len(self.command.stdout.read().strip().split('\n')) == 3
