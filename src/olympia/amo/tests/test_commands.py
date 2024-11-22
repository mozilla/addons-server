import io
import os
from importlib import import_module
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test.utils import override_settings

import pytest
from freezegun import freeze_time

from olympia.amo.management import BaseDataCommand, storage_structure
from olympia.amo.tests import TestCase, user_factory
from olympia.users.models import UserProfile


def sample_cron_job(*args):
    pass


@override_settings(CRON_JOBS={'sample_cron_job': 'olympia.amo.tests.test_commands'})
@mock.patch('olympia.amo.tests.test_commands.sample_cron_job')
def test_cron_command(_mock):
    assert _mock.call_count == 0
    call_command('cron', 'sample_cron_job', 'arg1', 'arg2')
    assert _mock.call_count == 1
    _mock.assert_called_with('arg1', 'arg2')

    call_command('cron', 'sample_cron_job', 'kwarg1=a', 'kwarg2=b')
    assert _mock.call_count == 2
    _mock.assert_called_with(kwarg1='a', kwarg2='b')


@override_settings(CRON_JOBS={'sample_cron_job': 'olympia.amo.tests.test_commands'})
def test_cron_command_no_job():
    with pytest.raises(CommandError) as error_info:
        call_command('cron')
    assert 'These jobs are available:' in str(error_info.value)
    assert 'sample_cron_job' in str(error_info.value)


def test_cron_command_invalid_job():
    with pytest.raises(CommandError) as error_info:
        call_command('cron', 'made_up_job')
    assert 'Unrecognized job name: made_up_job' in str(error_info.value)


def test_cron_jobs_setting():
    for name, path in settings.CRON_JOBS.items():
        module = import_module(path)
        getattr(module, name)


@pytest.mark.static_assets
def test_compress_assets_correctly_fetches_static_images(settings, tmpdir):
    """
    Make sure that `compress_assets` correctly fetches static assets
    such as icons and writes them correctly into our compressed
    and concatted files.

    Refs https://github.com/mozilla/addons-server/issues/8760
    """
    settings.MINIFY_BUNDLES = {'css': {'zamboni/_test_css': ['css/legacy/main.css']}}

    css_all = os.path.join(settings.STATIC_ROOT, 'css', 'zamboni', '_test_css-all.css')

    css_min = os.path.join(settings.STATIC_ROOT, 'css', 'zamboni', '_test_css-min.css')

    # Delete the files if they exist - they are specific to tests.
    try:
        os.remove(css_all)
    except FileNotFoundError:
        pass
    try:
        os.remove(css_min)
    except FileNotFoundError:
        pass

    # Capture output to avoid it being logged and allow us to validate it
    # later if needed
    out = io.StringIO()

    # Now run compress and collectstatic
    call_command('compress_assets', force=True, stdout=out)
    call_command('collectstatic', interactive=False, stdout=out)

    with open(css_all) as fobj:
        expected = 'background-image: url(../../img/icons/stars.png'
        assert expected in fobj.read()

    # Compressed doesn't have any whitespace between `background-image:` and
    # the url and the path is slightly different
    with open(css_min) as fobj:
        data = fobj.read()
        assert 'background-image:url(' in data
        assert 'img/icons/stars.png' in data


@pytest.mark.static_assets
def test_compress_assets_correctly_compresses_js(settings, tmpdir):
    """
    Make sure that `compress_assets` correctly calls the JS minifier and that
    it generates a minified file.
    """
    settings.MINIFY_BUNDLES = {'js': {'zamboni/_test_js': ['js/zamboni/global.js']}}

    js_all = os.path.join(settings.STATIC_ROOT, 'js', 'zamboni', '_test_js-all.js')
    js_min = os.path.join(settings.STATIC_ROOT, 'js', 'zamboni', '_test_js-min.js')

    # Delete the files if they exist - they are specific to tests.
    try:
        os.remove(js_all)
    except FileNotFoundError:
        pass
    try:
        os.remove(js_min)
    except FileNotFoundError:
        pass

    # Capture output to avoid it being logged and allow us to validate it
    # later if needed
    out = io.StringIO()

    # Now run compress and collectstatic
    call_command('compress_assets', force=True, stdout=out)
    call_command('collectstatic', interactive=False, stdout=out)

    # Files should exist now.
    assert os.path.getsize(js_all)
    assert os.path.getsize(js_min)


@pytest.mark.needs_locales_compilation
def test_generate_jsi18n_files():
    dirname = os.path.join(settings.STATIC_BUILD_PATH, 'js', 'i18n')
    assert os.path.exists(dirname)
    filename = os.path.join(dirname, 'fr.js')
    call_command('generate_jsi18n_files')
    # Regardless of whether or not the file existed before, it needs to exist
    # now.
    assert os.path.exists(filename), filename

    # Spot-check: Look for a string we know should be in the french file
    # (Translation for "Error").
    filename = os.path.join(dirname, 'fr.js')
    with open(filename) as f:
        content = f.read()
        assert 'Erreur' in content


class BaseTestDataCommand(TestCase):
    class Commands:
        reset_db = mock.call('reset_db', '--no-utf8', '--noinput')
        migrate = mock.call('migrate', '--noinput')
        data_seed = mock.call('data_seed')

        reindex = mock.call('reindex', '--wipe', '--force', '--noinput')
        load_initial_data = mock.call('loaddata', 'initial.json')
        import_prod_versions = mock.call('import_prod_versions')
        createsuperuser = mock.call(
            'createsuperuser',
            '--no-input',
            '--username',
            settings.LOCAL_ADMIN_USERNAME,
            '--email',
            settings.LOCAL_ADMIN_EMAIL,
        )
        load_zadmin_users = mock.call('loaddata', 'zadmin/users')
        generate_default_addons_for_frontend = mock.call(
            'generate_default_addons_for_frontend'
        )

        def data_dump(self, name='_init'):
            return mock.call('data_dump', '--name', name)

        def generate_addons(self, app, num_addons):
            return mock.call('generate_addons', '--app', app, num_addons)

        def generate_themes(self, num_themes):
            return mock.call('generate_themes', num_themes)

        def data_load(self, name='_init'):
            return mock.call('data_load', '--name', name)

        def db_backup(self, output_path):
            return mock.call(
                'dbbackup', output_path=output_path, interactive=False, compress=True
            )

        def db_restore(self, input_path):
            return mock.call(
                'dbrestore', input_path=input_path, interactive=False, uncompress=True
            )

        def media_backup(self, output_path):
            return mock.call(
                'mediabackup', output_path=output_path, interactive=False, compress=True
            )

        def media_restore(self, input_path):
            return mock.call(
                'mediarestore',
                input_path=input_path,
                interactive=False,
                uncompress=True,
                replace=True,
            )

    base_data_command = BaseDataCommand()
    backup_dir = '/data/olympia/backups'
    db_file = 'db.sql'
    storage_file = 'storage.tar'

    def setUp(self):
        self.mock_commands = self.Commands()

    def _assert_commands_called_in_order(self, mock_call_command, expected_commands):
        actual_commands = mock_call_command.mock_calls
        assert actual_commands == expected_commands, (
            f'Commands were not called in the expected order. '
            f'Expected: {expected_commands}, Actual: {actual_commands}'
        )


@override_settings(DATA_BACKUP_SKIP=False)
class TestInitializeDataCommand(BaseTestDataCommand):
    def setUp(self):
        super().setUp()
        patches = (
            (
                'mock_call_command',
                'olympia.amo.management.commands.initialize.call_command',
            ),
        )

        self.mocks = {}

        for mock_name, mock_path in patches:
            patcher = mock.patch(mock_path)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

        UserProfile.objects.filter(email=settings.LOCAL_ADMIN_EMAIL).delete()

    def with_local_admin(self):
        user_factory(
            username=settings.LOCAL_ADMIN_USERNAME, email=settings.LOCAL_ADMIN_EMAIL
        )

    @override_settings(DATA_BACKUP_SKIP=True)
    def test_handle_with_skip_data_initialize(self):
        """
        Test running the 'initialize' command with the DATA_BACKUP_SKIP flag set.
        Expected: nothing happens.
        """
        call_command('initialize')
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [],
        )

    @override_settings(DATA_BACKUP_SKIP=True)
    def test_handle_with_load_argument_and_skip_data_initialize(self):
        """
        Test running the 'initialize' command with both '--load' argument
        and DATA_BACKUP_SKIP flag. Expected: nothing happens.
        """
        call_command('initialize', load='test')
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [],
        )

    def test_handle_with_clean_and_load_arguments(self):
        """
        Test running the 'initialize' command with both '--clean' and '--load'
        arguments. Expected: Command should prioritize '--clean' and perform
        migration and seeding.
        """
        name = 'test'
        call_command('initialize', clean=True, load=name)
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.data_seed,
            ],
        )

    def test_handle_with_clean_argument_no_local_admin(self):
        """
        Test running the 'initialize' command with the '--clean' argument
        when no local admin exists. Expected: The database is migrated, seeded
        with fresh data, loaded from backup if specified, and reindexed.
        """
        call_command('initialize', clean=True)
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.data_seed,
            ],
        )

    def test_handle_without_clean_or_load_with_local_admin(self):
        """
        Test running the 'initialize' command without '--clean' or '--load'
        arguments when a local admin exists. Expected: The database is migrated
        and reindexed without seeding or loading data.
        """
        self.with_local_admin()
        call_command('initialize')
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.migrate,
                self.mock_commands.reindex,
            ],
        )

    def test_handle_without_clean_or_load_without_local_admin(self):
        """
        Test running the 'initialize' command without '--clean' or '--load'
        arguments when no local admin exists. Expected: The database is
        migrated, seeded with initial data, and reindexed.
        """
        call_command('initialize')
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.data_seed,
            ],
        )

    def test_handle_migration_failure(self):
        """
        Test running the 'initialize' command when the 'migrate' command fails.
        Expected: The command exits with an error and does not proceed to seeding
        or loading data.
        """
        self.with_local_admin()
        self.mocks['mock_call_command'].side_effect = Exception('test')
        with pytest.raises(Exception) as context:
            call_command('initialize')
        assert 'test' in str(context.value)
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.migrate,
            ],
        )

    @mock.patch('olympia.amo.management.commands.initialize.UserProfile.objects.filter')
    def test_handle_mysql_exception(self, mock_filter):
        mock_filter.return_value.exists.side_effect = Exception('test')

        call_command('initialize')
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [self.mock_commands.data_seed],
        )


class TestBaseDataCommand(BaseTestDataCommand):
    def setUp(self):
        super().setUp()

    def test_backup_dir_path(self):
        name = 'test_backup'
        expected_path = os.path.join(self.backup_dir, name)

        actual_path = self.base_data_command.backup_dir_path(name)
        assert (
            actual_path == expected_path
        ), f'Expected {expected_path}, got {actual_path}'

    def test_backup_db_path(self):
        name = 'db_backup'
        expected_path = os.path.join(self.backup_dir, name, self.db_file)
        actual_path = self.base_data_command.backup_db_path(name)
        assert (
            actual_path == expected_path
        ), f'Expected {expected_path}, got {actual_path}'

    def test_backup_storage_path(self):
        name = 'storage_backup'
        expected_path = os.path.join(self.backup_dir, name, self.storage_file)
        actual_path = self.base_data_command.backup_storage_path(name)
        assert (
            actual_path == expected_path
        ), f'Expected {expected_path}, got {actual_path}'

    @mock.patch('olympia.amo.management.shutil.rmtree')
    @mock.patch('olympia.amo.management.logging')
    def test_clean_dir(self, mock_logging, mock_rmtree):
        name = 'cleanup_test'
        backup_path = self.base_data_command.backup_dir_path(name)

        self.base_data_command.clean_dir(name)

        mock_logging.info.assert_called_with(f'Clearing {backup_path}')
        mock_rmtree.assert_called_with(backup_path, ignore_errors=True)

    @mock.patch('olympia.amo.management.os.path.exists')
    @mock.patch('olympia.amo.management.shutil.rmtree')
    @mock.patch('olympia.amo.management.os.makedirs')
    def test_make_dir_existing_path_no_force(
        self, mock_makedirs, mock_rmtree, mock_exists
    ):
        name = 'existing_dir'
        mock_exists.return_value = True

        with self.assertRaises(CommandError) as context:
            self.base_data_command.make_dir(name, force=False)
            assert 'Directory already exists' in str(context.exception)

    @mock.patch('olympia.amo.management.os.path.exists')
    @mock.patch('olympia.amo.management.shutil.rmtree')
    @mock.patch('olympia.amo.management.os.makedirs')
    def test_make_dir_existing_path_with_force(
        self, mock_makedirs, mock_rmtree, mock_exists
    ):
        name = 'existing_dir_force'
        backup_path = self.base_data_command.backup_dir_path(name)
        mock_exists.return_value = True

        self.base_data_command.make_dir(name, force=True)

        mock_exists.assert_called_with(backup_path)
        mock_rmtree.assert_called_with(backup_path, ignore_errors=True)
        mock_makedirs.assert_called_with(backup_path, exist_ok=True)

    @mock.patch('olympia.amo.management.os.path.exists')
    @mock.patch('olympia.amo.management.os.makedirs')
    def test_make_dir_non_existing_path(self, mock_makedirs, mock_exists):
        name = 'new_dir'
        backup_path = self.base_data_command.backup_dir_path(name)
        mock_exists.return_value = False

        self.base_data_command.make_dir(name, force=False)

        mock_exists.assert_called_with(backup_path)
        mock_makedirs.assert_called_with(backup_path, exist_ok=True)

    @mock.patch('olympia.amo.management.shutil.rmtree')
    @mock.patch('olympia.amo.management.os.makedirs')
    def test_clean_storage(self, mock_makedirs, mock_rmtree):
        self.base_data_command.clean_storage()

        def walk_keys(root, dir_dict):
            for key, value in dir_dict.items():
                if isinstance(value, dict):
                    walk_keys(os.path.join(root, key), value)
                else:
                    keys.append(os.path.join(root, key))

        keys = []
        walk_keys(settings.STORAGE_ROOT, storage_structure)

        assert keys == [
            os.path.join(settings.STORAGE_ROOT, 'files'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/addons'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/data'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/file_viewer'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/guarded-addons'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/icon'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/log'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/persona_header'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/preview'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/test'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/tmp/uploads'),
            os.path.join(settings.STORAGE_ROOT, 'shared_storage/uploads'),
        ]

        for key in keys:
            assert mock.call(key, ignore_errors=True) in mock_rmtree.mock_calls
            assert mock.call(key, exist_ok=True) in mock_makedirs.mock_calls


class TestDumpDataCommand(BaseTestDataCommand):
    def setUp(self):
        super().setUp()
        patches = (
            (
                'mock_make_dir',
                'olympia.amo.management.commands.data_dump.BaseDataCommand.make_dir',
            ),
            (
                'mock_call_command',
                'olympia.amo.management.commands.data_dump.call_command',
            ),
            (
                'mock_clean_dir',
                'olympia.amo.management.commands.data_dump.BaseDataCommand.clean_dir',
            ),
        )
        self.mocks = {}

        for mock_name, mock_path in patches:
            patcher = mock.patch(mock_path)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

    @freeze_time('2023-06-26 11:00:44')
    def test_default_name(self):
        print('backup', self.backup_dir)
        backup_dir = os.path.join(self.backup_dir, '20230626110044')
        db_path = os.path.join(backup_dir, self.db_file)
        storage_path = os.path.join(backup_dir, self.storage_file)

        call_command('data_dump')
        self.mocks['mock_make_dir'].assert_called_with(backup_dir, force=False)
        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.db_backup(db_path),
                self.mock_commands.media_backup(storage_path),
            ],
        )

    def test_custom_name(self):
        name = 'test'
        backup_dir = os.path.join(self.backup_dir, name)

        call_command('data_dump', name=name)
        self.mocks['mock_make_dir'].assert_called_with(backup_dir, force=False)

    def test_failure(self):
        name = 'test'
        backup_dir = os.path.join(self.backup_dir, name)
        self.mocks['mock_call_command'].side_effect = Exception('banana')

        with pytest.raises(Exception) as context:
            call_command('data_dump', name=name)
        assert 'banana' in str(context.value)
        self.mocks['mock_clean_dir'].assert_called_with(backup_dir)


class TestLoadDataCommand(BaseTestDataCommand):
    def setUp(self):
        super().setUp()

        patcher = mock.patch('olympia.amo.management.commands.data_load.call_command')
        self.addCleanup(patcher.stop)
        self.mock_call_command = patcher.start()

    def test_missing_name(self):
        with pytest.raises(CommandError):
            call_command('data_load')

    @mock.patch('olympia.amo.management.commands.data_load.os.path.exists')
    @mock.patch('olympia.amo.management.commands.data_load.cache.clear')
    def test_clear_cache(self, mock_clear_cache, mock_exists):
        mock_exists.return_value = True
        call_command('data_load', name='test_backup')
        mock_clear_cache.assert_called_once()

    @mock.patch('olympia.amo.management.commands.data_load.os.path.exists')
    def test_loads_correct_path(self, mock_exists):
        mock_exists.return_value = True
        name = 'test_backup'
        backup_dir = os.path.join(self.backup_dir, name)
        db_path = os.path.join(backup_dir, self.db_file)
        storage_path = os.path.join(backup_dir, self.storage_file)

        call_command('data_load', name=name)

        self._assert_commands_called_in_order(
            self.mock_call_command,
            [
                self.mock_commands.db_restore(db_path),
                self.mock_commands.media_restore(storage_path),
                self.mock_commands.reindex,
            ],
        )

    @mock.patch('olympia.amo.management.commands.data_load.os.path.exists')
    def test_data_load_with_missing_db(self, mock_exists):
        mock_exists.return_value = False
        with pytest.raises(CommandError) as context:
            call_command('data_load', name='test_backup')
        assert 'DB backup not found' in str(context.value)

    @mock.patch('olympia.amo.management.commands.data_load.os.path.exists')
    def test_data_load_with_missing_storage(self, mock_exists):
        storage_path = os.path.join(self.backup_dir, 'test_backup', self.storage_file)

        mock_exists.side_effect = lambda path: path != storage_path

        with pytest.raises(CommandError) as context:
            call_command('data_load', name='test_backup')
        assert 'Storage backup not found' in str(context.value)


class TestSeedDataCommand(BaseTestDataCommand):
    def setUp(self):
        super().setUp()

        patches = (
            (
                'mock_call_command',
                'olympia.amo.management.commands.data_seed.call_command',
            ),
            (
                'mock_clean_dir',
                'olympia.amo.management.commands.data_seed.BaseDataCommand.clean_dir',
            ),
            (
                'mock_clean_storage',
                'olympia.amo.management.commands.data_seed.BaseDataCommand.clean_storage',
            ),
        )

        self.mocks = {}

        for mock_name, mock_path in patches:
            patcher = mock.patch(mock_path)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

    def test_default(self):
        call_command('data_seed')

        self.mocks['mock_clean_dir'].assert_called_once_with(
            self.base_data_command.data_backup_init
        )
        self.mocks['mock_clean_storage'].assert_called_once()

        self._assert_commands_called_in_order(
            self.mocks['mock_call_command'],
            [
                self.mock_commands.reset_db,
                self.mock_commands.migrate,
                self.mock_commands.load_initial_data,
                self.mock_commands.import_prod_versions,
                self.mock_commands.createsuperuser,
                self.mock_commands.load_zadmin_users,
                self.mock_commands.generate_addons('firefox', 10),
                self.mock_commands.generate_addons('android', 10),
                self.mock_commands.generate_themes(5),
                self.mock_commands.generate_default_addons_for_frontend,
                self.mock_commands.data_dump(self.base_data_command.data_backup_init),
                self.mock_commands.data_load(self.base_data_command.data_backup_init),
            ],
        )
