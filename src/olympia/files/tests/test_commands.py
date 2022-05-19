import io
import os
from datetime import timedelta
from unittest import mock

from django.conf import settings

from olympia.amo.tests import addon_factory, TestCase
from olympia.files.management.commands.migrate_files_to_new_structure import (
    Command as MigrateFilesToNewStructure,
)
from olympia.files.management.commands.migrate_guarded_addons import (
    Command as MigrateGuardedAddons,
)


class TestMigrateFilesToNewStructure(TestCase):
    def setUp(self):
        self.command = MigrateFilesToNewStructure()
        self.command.verbosity = 1
        self.command.stderr = io.StringIO()
        self.command.stdout = io.StringIO()

    def test_print_eta(self):
        self.command.print_eta(
            elapsed=timedelta(seconds=0, microseconds=191332),
            processed_count=4,
            remaining_count=815162342,
        )
        self.command.stdout.seek(0)
        assert (
            self.command.stdout.read()
            == 'ETA 451 days, 7:01:00 ; Remaining entries 815162342\n'
        )

    def test_print_eta_shorter(self):
        self.command.print_eta(
            elapsed=timedelta(minutes=20, seconds=30, microseconds=424567),
            processed_count=12345,
            remaining_count=678,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:01:07 ; Remaining entries 678\n'

    def test_print_eta_0_migrated(self):
        self.command.print_eta(
            elapsed=timedelta(seconds=1),
            processed_count=0,
            remaining_count=9999,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA Unknown ; Remaining entries 9999\n'

    def test_print_eta_0_remaining(self):
        self.command.print_eta(
            elapsed=timedelta(hours=8, minutes=7, seconds=6, microseconds=540530),
            processed_count=1000000000,
            remaining_count=0,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:00:00 ; Remaining entries 0\n'

    def test_migrate_file(self):
        file_ = addon_factory(
            pk=123456,
            slug='someaddon',
            version_kw={'version': '42.0'},
            file_kw={'is_signed': True},
        ).current_version.file
        file_.update(file='bar.xpi')
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            rval = self.command.migrate_file('123456', 'bar.xpi')
        expected_source_path = os.path.join(settings.ADDONS_PATH, '123456', 'bar.xpi')
        expected_target_path = os.path.join(
            settings.ADDONS_PATH, '56/3456/123456', 'someaddon-42.0.xpi'
        )
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((expected_source_path, expected_target_path),)
        file_.reload()
        assert file_.file.path == expected_target_path
        assert rval is True
        self.command.stderr.seek(0)
        assert self.command.stderr.read() == ''

    def test_migrate_file_not_in_db(self):
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            rval = self.command.migrate_file('123456', 'bar.xpi')
        assert mocked_link.call_count == 0
        assert rval is False
        self.command.stderr.seek(0)
        assert (
            self.command.stderr.read()
            == 'Ignoring likely obsolete or already migrated 123456/bar.xpi'
        )

    def test_migrate_file_already_exists(self):
        file_ = addon_factory(
            pk=123456,
            slug='someaddon',
            version_kw={'version': '42.0'},
            file_kw={'is_signed': True},
        ).current_version.file
        file_.update(file='bar.xpi')
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            mocked_link.side_effect = FileExistsError
            self.command.migrate_file('123456', 'bar.xpi')
        expected_source_path = os.path.join(settings.ADDONS_PATH, '123456', 'bar.xpi')
        expected_target_path = os.path.join(
            settings.ADDONS_PATH, '56/3456/123456', 'someaddon-42.0.xpi'
        )
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((expected_source_path, expected_target_path),)
        # We ignored the error and proceeded as normal (file had already been
        # migrated on the filesystem but database had not been updated yet, now
        # it should be).
        file_.reload()
        assert file_.file.path == expected_target_path
        self.command.stderr.seek(0)
        assert self.command.stderr.read() == 'Ignoring already migrated 123456/bar.xpi'

    def test_migrate_directory_contents(self):
        addon_path = os.path.join(settings.ADDONS_PATH, '4815162342')
        os.makedirs(addon_path)
        file_path = os.path.join(addon_path, 'bar.xpi')
        with open(file_path, 'w') as f:
            f.write('a')
        with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
            self.command.migrate_directory_contents('4815162342')
        assert migrate_file_mock.call_count == 1
        assert migrate_file_mock.call_args[0] == ('4815162342', 'bar.xpi')

    def test_migrate_directory_contents_ignore_non_zip_or_xpi(self):
        addon_path = os.path.join(settings.ADDONS_PATH, '4815162342')
        os.makedirs(addon_path)
        for filename in ('bar.xpi', 'baz.zip', 'xyz.png'):
            file_path = os.path.join(addon_path, filename)
            with open(file_path, 'w') as f:
                f.write('a')
        with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
            self.command.migrate_directory_contents('4815162342')
        assert migrate_file_mock.call_count == 2
        expected = [
            ('4815162342', 'bar.xpi'),
            ('4815162342', 'baz.zip'),
        ]
        actual = sorted(
            (
                migrate_file_mock.call_args_list[0][0],
                migrate_file_mock.call_args_list[1][0],
            )
        )
        assert actual == expected

    def test_migrate_directory_contents_empty_dir(self):
        addon_path = os.path.join(settings.ADDONS_PATH, '4815162342')
        os.makedirs(addon_path)
        with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
            self.command.migrate_directory_contents('4815162342')
        assert migrate_file_mock.call_count == 0

    @mock.patch(
        'olympia.files.management.commands.migrate_files_to_new_structure.os.scandir'
    )
    def test_migrate(self, scandir_mock):
        # Return 2001 addon directories and a couple additional entries that should be
        # ignored.
        scandir_mock.return_value = [
            mock.Mock(
                spec=os.DirEntry,
                _name=str(x),
                path=os.path.join(settings.ADDONS_PATH, str(x)),
            )
            for x in range(1, 2002)
        ] + [
            mock.Mock(
                spec=os.DirEntry,
                _name='.123456',
                path=os.path.join(settings.ADDONS_PATH, '.123456'),
            ),
            mock.Mock(
                spec=os.DirEntry,
                _name='temp',
                path=os.path.join(settings.ADDONS_PATH, 'temp'),
            ),
        ]
        for mocked in scandir_mock.return_value:
            mocked.name = (
                mocked._name
            )  # Ugly but `name` is a special attribute in mocks.
        with mock.patch.object(
            self.command, 'migrate_directory_contents'
        ) as migrate_directory_contents_mock:
            migrate_directory_contents_mock.return_value = 1
            self.command.migrate()
        # We're mocking migrate_directory_contents() so scandir() should have
        # been called only once.
        assert scandir_mock.call_count == 1
        assert scandir_mock.call_args == ((settings.ADDONS_PATH,),)
        assert migrate_directory_contents_mock.call_count == 2001
        assert migrate_directory_contents_mock.call_args_list[23] == (('24',),)
        self.command.stdout.seek(0)
        # We should have printed the ETA 3 times and added a summary in the 4th
        # line.
        assert len(self.command.stdout.read().strip().split('\n')) == 4


class TestMigrateGuardedAddons(TestCase):
    def setUp(self):
        self.command = MigrateGuardedAddons()
        self.command.verbosity = 1
        self.command.stderr = io.StringIO()
        self.command.stdout = io.StringIO()
        self.command.guarded_addons_path = os.path.join(
            settings.STORAGE_ROOT, 'guarded-addons'
        )

    def test_migrate_file(self):
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            self.command.migrate_file('foo', 'bar.xpi')
        expected_source_path = os.path.join(
            self.command.guarded_addons_path, 'foo', 'bar.xpi'
        )
        expected_target_path = os.path.join(settings.ADDONS_PATH, 'foo', 'bar.xpi')
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((expected_source_path, expected_target_path),)

    def test_migrate_file_already_exists(self):
        self.command.guarded_addons_path = '/tmp/guarded-addons'
        with mock.patch(
            'olympia.files.management.commands.migrate_guarded_addons.os.link'
        ) as mocked_link:
            mocked_link.side_effect = FileExistsError
            self.command.migrate_file('foo', 'bar.xpi')
        expected_source_path = os.path.join(
            self.command.guarded_addons_path, 'foo', 'bar.xpi'
        )
        expected_target_path = os.path.join(settings.ADDONS_PATH, 'foo', 'bar.xpi')
        assert mocked_link.call_count == 1
        assert mocked_link.call_args == ((expected_source_path, expected_target_path),)
        self.command.stderr.seek(0)
        assert (
            self.command.stderr.read()
            == 'Ignoring already existing /tmp/guarded-addons/foo/bar.xpi'
        )

    def test_migrate_addon(self):
        addon_path = os.path.join(self.command.guarded_addons_path, 'foo')
        os.makedirs(addon_path)
        file_path = os.path.join(addon_path, 'bar.xpi')
        with open(file_path, 'w') as f:
            f.write('a')
        with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
            self.command.migrate_addon('foo')
        assert migrate_file_mock.call_count == 1
        assert migrate_file_mock.call_args[0] == ('foo', 'bar.xpi')

    def test_migrate_addon_empty_dir(self):
        addon_path = os.path.join(self.command.guarded_addons_path, 'foo')
        os.makedirs(addon_path)
        with mock.patch.object(self.command, 'migrate_file') as migrate_file_mock:
            self.command.migrate_addon('foo')
        assert migrate_file_mock.call_count == 0

    def test_print_eta(self):
        self.command.print_eta(
            elapsed=timedelta(seconds=0, microseconds=191332),
            entries_migrated=4,
            entries_remaining=815162342,
        )
        self.command.stdout.seek(0)
        assert (
            self.command.stdout.read()
            == 'ETA 451 days, 7:01:00 ; Remaining entries 815162342\n'
        )

    def test_print_eta_shorter(self):
        self.command.print_eta(
            elapsed=timedelta(minutes=20, seconds=30, microseconds=424567),
            entries_migrated=12345,
            entries_remaining=678,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:01:07 ; Remaining entries 678\n'

    def test_print_eta_0_migrated(self):
        self.command.print_eta(
            elapsed=timedelta(seconds=1),
            entries_migrated=0,
            entries_remaining=9999,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA Unknown ; Remaining entries 9999\n'

    def test_print_eta_0_remaining(self):
        self.command.print_eta(
            elapsed=timedelta(hours=8, minutes=7, seconds=6, microseconds=540530),
            entries_migrated=1000000000,
            entries_remaining=0,
        )
        self.command.stdout.seek(0)
        assert self.command.stdout.read() == 'ETA 0:00:00 ; Remaining entries 0\n'

    @mock.patch('olympia.files.management.commands.migrate_guarded_addons.os.scandir')
    def test_migrate(self, scandir_mock):
        # Return 2001 addon directories and a stray .whatever that should be ignored.
        scandir_mock.return_value = [
            mock.Mock(
                spec=os.DirEntry,
                _name=str(x),
                path=os.path.join(self.command.guarded_addons_path, str(x)),
            )
            for x in range(1, 2002)
        ] + [
            mock.Mock(
                spec=os.DirEntry,
                _name='.whatever',
                path=os.path.join(self.command.guarded_addons_path, '.whatever'),
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
        assert scandir_mock.call_args == ((self.command.guarded_addons_path,),)
        assert migrate_addon_mock.call_count == 2001
        assert migrate_addon_mock.call_args_list[23] == (('24',),)
        self.command.stdout.seek(0)
        # We should have printed the ETA 3 times.
        assert len(self.command.stdout.read().strip().split('\n')) == 3
