import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.operations.base import Operation

from freezegun import freeze_time
from pyparsing import Path

from olympia.amo.tests import TestCase
from olympia.core.management.commands import BaseMigrationCommand
from olympia.core.management.commands.migrate_waffle import Action


class TestSnapshotMixin:
    def assertMatchesSnapshot(self, result, snapshot_dir=__file__):
        snapshot_dir = Path(snapshot_dir).parent / 'snapshots' / self.__class__.__name__
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        name = self._testMethodName

        snapshot_path = snapshot_dir / f'{name}.txt'

        if not snapshot_path.exists():
            snapshot_path.write_text(result)

        with snapshot_path.open('r') as f:
            snapshot = f.read()

        self.assertEqual(result, snapshot)


@freeze_time('2025-04-04 04:04')
class TestBaseMigrationCommand(TestCase, TestSnapshotMixin):
    def setUp(self):
        patch_graph = mock.patch(
            'olympia.core.management.commands.BaseMigrationCommand.graph'
        )
        self.graph = patch_graph.start()
        self.graph.leaf_nodes.return_value = []
        self.addCleanup(patch_graph.stop)

        patch_stdout = mock.patch(
            'olympia.core.management.commands.BaseMigrationCommand.print'
        )
        self.print = patch_stdout.start()
        self.addCleanup(patch_stdout.stop)

    class TestOperation(Operation):
        def __init__(self, name, *args, **kwargs):
            self.name = name
            super().__init__(*args, **kwargs)

        def deconstruct(self):
            return (
                'test_operation',
                [self.name],
                {},
            )

    class TestCommand(BaseMigrationCommand):
        def get_name(self, *args, **options):
            return 'test_name'

        def get_operation(self, *args, **options):
            return TestBaseMigrationCommand.TestOperation('test_argument')

        def extend_arguments(self, parser):
            parser.add_argument('--test-argument', type=str, help='Test argument')

    def test_unimplemented_methods_should_raise(self):
        class Command(BaseMigrationCommand):
            pass

        with self.assertRaises(NotImplementedError):
            Command().handle()

        with self.assertRaises(NotImplementedError):
            Command().get_name()

        with self.assertRaises(NotImplementedError):
            Command().get_operation()

        with self.assertRaises(NotImplementedError):
            Command().extend_arguments(None)

    def test_get_migration_name(self):
        command = self.TestCommand()
        self.assertEqual(command.get_name(), 'test_name')

    def test_adds_specified_operations(self):
        command = self.TestCommand()
        command.handle(dry_run=True, app_label='core')

        filename, output = self.print.call_args_list[0][0]
        assert filename.endswith('0001_test_name.py')
        self.assertMatchesSnapshot(output)

    def test_includes_extended_arguments(self):
        command = self.TestCommand()
        mock_add_argument = mock.MagicMock()
        mock_parser = mock.Mock()
        mock_parser.add_argument.side_effect = mock_add_argument
        command.add_arguments(mock_parser)

        assert (
            mock.call('--test-argument', type=str, help='Test argument')
            in mock_add_argument.call_args_list
        )

    def test_correct_migration_file(self):
        """
        Set's the writer.path to a temporary directory and expects
        the migration file to be written there.
        """
        tmp_dir = tempfile.mkdtemp()
        output_path = Path(tmp_dir) / '0001_test_name.py'
        mock_writer = mock.MagicMock()
        mock_writer.path = output_path.as_posix()
        mock_writer.as_string.return_value = 'mock migration file'

        with mock.patch(
            'olympia.core.management.commands.BaseMigrationCommand.writer'
        ) as patch_writer:
            patch_writer.return_value = mock_writer

            command = self.TestCommand()
            command.handle(app_label='core')

        assert output_path.exists()
        assert output_path.read_text() == 'mock migration file'

    def test_adds_dependencies_from_previous_migrations(self):
        migrations = [('core', f'{x:04d}_test_name') for x in range(1, 3)]
        self.graph.leaf_nodes.return_value = migrations

        command = self.TestCommand()
        command.handle(app_label='core', dry_run=True)
        filename, output = self.print.call_args_list[0][0]
        assert filename.endswith('0003_test_name.py')
        self.assertMatchesSnapshot(output)


@freeze_time('2025-04-04 04:04')
class TestMigrateWaffle(TestCase, TestSnapshotMixin):
    def test_missing_required_arguments_should_raise(self):
        test_cases = [
            ('migrate_waffle', {}),
            ('migrate_waffle', 'fake_app', {}),
            ('migrate_waffle', 'core', {}),
            ('migrate_waffle', 'core', 'test_switch', {'action': Action.RENAME}),
        ]

        for args in test_cases:
            args, kwargs = args[:-1], args[-1]
            with (
                self.subTest(args=args, kwargs=kwargs),
                self.assertRaises(CommandError),
            ):
                call_command(*args, **kwargs, dry_run=True)

    def test_add_waffle_switch(self):
        output = call_command(
            'migrate_waffle',
            'core',
            'test_switch',
            action=Action.ADD,
            dry_run=True,
        )
        self.assertMatchesSnapshot(output)

    def test_delete_waffle_switch(self):
        output = call_command(
            'migrate_waffle',
            'core',
            'test_switch',
            action=Action.DELETE,
            dry_run=True,
        )
        self.assertMatchesSnapshot(output)

    def test_rename_waffle_switch(self):
        output = call_command(
            'migrate_waffle',
            'core',
            'test_switch',
            action=Action.RENAME,
            new_name='new_test_switch',
            dry_run=True,
        )
        self.assertMatchesSnapshot(output)
