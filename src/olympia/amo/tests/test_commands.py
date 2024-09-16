import io
import os
from datetime import datetime, timedelta
from importlib import import_module
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test.utils import override_settings

import pytest
from MySQLdb import Error as MySQLError

from olympia.addons.models import Preview
from olympia.amo.management.commands.get_changed_files import (
    collect_addon_icons,
    collect_addon_previews,
    collect_blocklist,
    collect_editoral,
    collect_files,
    collect_git,
    collect_sources,
    collect_theme_previews,
    collect_user_pics,
)
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.amo.utils import id_to_path
from olympia.blocklist.utils import datetime_to_ts
from olympia.files.models import File, files_upload_to_callback
from olympia.git.utils import AddonGitRepository
from olympia.hero.models import PrimaryHeroImage
from olympia.versions.models import VersionPreview, source_upload_path


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


class TestGetChangedFilesCommand(TestCase):
    fixtures = ['base/addon_5299_gcal']

    def setUp(self):
        self.yesterday = datetime.now() - timedelta(hours=24)
        self.newer = self.yesterday + timedelta(seconds=10)
        self.older = self.yesterday - timedelta(seconds=10)

    def test_command(self):
        user = user_factory()
        PrimaryHeroImage.objects.create()

        with io.StringIO() as out:
            call_command('get_changed_files', '1', stdout=out)
            assert out.getvalue() == (
                f'{user.picture_dir}\n'
                f'{os.path.join(settings.MEDIA_ROOT, "hero-featured-image")}\n'
            )

    def test_collect_user_pics(self):
        changed = user_factory()
        unchanged = user_factory()
        unchanged.update(modified=self.older)
        assert unchanged.modified < self.yesterday
        with self.assertNumQueries(1):
            assert collect_user_pics(self.yesterday) == [changed.picture_dir]

    def test_collect_files(self):
        new_file = File.objects.get(id=33046)
        new_file.update(modified=self.newer)
        version_factory(
            addon=new_file.addon,
            file_kw={'file': files_upload_to_callback(new_file, 'foo.xpi')},
        )  # an extra file to check de-duping
        old_file = addon_factory().current_version.file
        old_file.update(modified=self.older)
        version_factory(addon=new_file.addon, file_kw={'file': None})  # no file
        assert old_file.modified < self.yesterday
        with self.assertNumQueries(1):
            assert collect_files(self.yesterday) == [
                os.path.dirname(new_file.file.path)
            ]

    def test_collect_sources(self):
        changed = addon_factory().current_version
        changed.update(source=source_upload_path(changed, 'foo.zip'))
        unchanged = addon_factory().current_version
        unchanged.update(modified=self.older)
        no_source_version = version_factory(addon=changed.addon, source=None)
        assert unchanged.modified < self.yesterday
        with self.assertNumQueries(1):
            assert collect_sources(self.yesterday) == [
                os.path.join(
                    settings.MEDIA_ROOT,
                    'version_source',
                    id_to_path(no_source_version.id),
                ),
                os.path.dirname(changed.source.path),
            ]

    def test_collect_addon_previews(self):
        preview1 = Preview.objects.create(addon=addon_factory())
        preview2 = Preview.objects.create(addon=addon_factory())
        older_preview = Preview.objects.create(
            addon=addon_factory(), id=preview1.id + 1000
        )
        older_preview.update(created=self.older)
        assert (preview1.id // 1000) == (preview2.id // 1000)
        assert (preview1.id // 1000) != (older_preview.id // 1000)
        assert os.path.dirname(preview1.image_path) == os.path.dirname(
            preview2.image_path
        )
        with self.assertNumQueries(1):
            assert sorted(collect_addon_previews(self.yesterday)) == [
                # only one set of dirs because 1 and 2 are in same subdirs
                os.path.dirname(preview1.image_path),
                os.path.dirname(preview1.original_path),
                os.path.dirname(preview1.thumbnail_path),
            ]

    def test_collect_theme_previews(self):
        preview1 = VersionPreview.objects.create(
            version=addon_factory().current_version
        )
        preview2 = VersionPreview.objects.create(
            version=addon_factory().current_version
        )
        older_preview = VersionPreview.objects.create(
            version=addon_factory().current_version, id=preview1.id + 1000
        )
        older_preview.update(created=self.older)
        assert (preview1.id // 1000) == (preview2.id // 1000)
        assert (preview1.id // 1000) != (older_preview.id // 1000)
        assert os.path.dirname(preview1.image_path) == os.path.dirname(
            preview2.image_path
        )
        with self.assertNumQueries(1):
            assert sorted(collect_theme_previews(self.yesterday)) == [
                # only one set of dirs because 1 and 2 are in same subdirs
                os.path.dirname(preview1.image_path),
                os.path.dirname(preview1.original_path),
                os.path.dirname(preview1.thumbnail_path),
            ]

    def test_collect_addon_icons(self):
        changed = addon_factory()
        unchanged = addon_factory()
        unchanged.update(modified=self.older)
        assert unchanged.modified < self.yesterday
        with self.assertNumQueries(1):
            assert collect_addon_icons(self.yesterday) == [changed.get_icon_dir()]

    def test_collect_editoral(self):
        image1 = PrimaryHeroImage.objects.create()
        image1.update(modified=self.older)
        image2 = PrimaryHeroImage.objects.create()
        image2.update(modified=self.older)
        # no new hero images so no dir
        assert collect_editoral(self.yesterday) == []
        image1.update(modified=self.newer)
        image2.update(modified=self.newer)
        # one or more updated hero images match then the root should be returned
        with self.assertNumQueries(1):
            assert collect_editoral(self.yesterday) == [
                os.path.join(settings.MEDIA_ROOT, 'hero-featured-image')
            ]

    def test_collect_git(self):
        new_file = File.objects.get(id=33046)
        new_file.update(modified=self.newer)
        version_factory(addon=new_file.addon)  # an extra file to check de-duping
        old_file = addon_factory().current_version.file
        old_file.update(modified=self.older)
        assert old_file.modified < self.yesterday
        with self.assertNumQueries(1):
            assert collect_git(self.yesterday) == [
                AddonGitRepository(new_file.addon).git_repository_path
            ]

    def test_collect_blocklist(self):
        class FakeEntry:
            def __init__(self, name, is_dir=True):
                self.name = str(name)
                self._is_dir = is_dir

            def is_dir(self):
                return self._is_dir

            @property
            def path(self):
                return f'foo/{self.name}'

        newerer = self.newer + timedelta(seconds=10)
        with mock.patch(
            'olympia.amo.management.commands.get_changed_files.scandir'
        ) as scandir_mock:
            scandir_mock.return_value = [
                FakeEntry('fooo'),  # not a datetime
                FakeEntry(datetime_to_ts(self.older)),  # too old
                FakeEntry(datetime_to_ts(self.newer), False),  # not a dir
                FakeEntry(datetime_to_ts(newerer)),  # yes
            ]
            with self.assertNumQueries(0):
                assert collect_blocklist(self.yesterday) == [
                    f'foo/{datetime_to_ts(newerer)}'
                ]


def scenario(
    db_exists=False,
    index_exists=False,
    force_db=False,
    skip_seed=False,
    skip_index=False,
    expected_queries=None,
    expected_commands=None,
):
    """
    Return a tuple of arguments for the test_scenarios function.
    Includes defaults for the baseline scenario of a
    totally fresh DB and index with no arguments.
    """
    return (
        db_exists,
        index_exists,
        force_db,
        skip_seed,
        skip_index,
        expected_queries if expected_queries is not None else ['CREATE_DB'],
        expected_commands
        if expected_commands is not None
        else ['MIGRATE', 'INITIAL_DATA', 'SEED_DATA', 'REINDEX'],
    )


@override_settings(DEBUG=True)
@pytest.mark.parametrize(
    'db_exists,index_exists,force_db,skip_seed,skip_index,expected_queries,expected_commands',
    [
        scenario(),
        # Skip seeding will remove 'SEED_DATA' from the expected commands.
        # Even if the DB doesn't exist
        scenario(
            db_exists=False,
            skip_seed=True,
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'REINDEX'],
        ),
        # Skip indexing will remove 'REINDEX' from the expected commands.
        # Even if the index doesn't exist
        scenario(
            index_exists=False,
            skip_index=True,
            expected_queries=['CREATE_DB'],
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'SEED_DATA'],
        ),
        # If the index exists, but the db does not, and we don't skip seeding
        # We reindex because there is new data in the db that needs to be indexed
        scenario(
            db_exists=False,
            index_exists=True,
            skip_seed=False,
            skip_index=False,
            expected_queries=['CREATE_DB'],
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'SEED_DATA', 'REINDEX'],
        ),
        # Similar to above, but instead we skip seeding with a non existant index
        # seed data is removed but reindexing is needed to reacreate it
        scenario(
            db_exists=False,
            index_exists=False,
            skip_seed=True,
            skip_index=False,
            expected_queries=['CREATE_DB'],
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'REINDEX'],
        ),
        # Even if the db exists, if we force db and don't skip seeding
        # we drop existing db and reseed the new one
        scenario(
            db_exists=True,
            force_db=True,
            skip_seed=False,
            expected_queries=['DROP_DB', 'CREATE_DB'],
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'SEED_DATA', 'REINDEX'],
        ),
        # Same as above but we can still skip reindexing by skipping it
        scenario(
            db_exists=True,
            force_db=True,
            skip_seed=False,
            skip_index=True,
            expected_queries=['DROP_DB', 'CREATE_DB'],
            expected_commands=['MIGRATE', 'INITIAL_DATA', 'SEED_DATA'],
        ),
        # we don't load initial data if we are not creating a db
        # However we do reindex if not skipping it
        scenario(
            db_exists=True,
            force_db=False,
            expected_queries=[],
            expected_commands=['MIGRATE', 'REINDEX'],
        ),
        # Similar as above but we skip reindexing
        scenario(
            db_exists=True,
            force_db=False,
            skip_index=True,
            expected_queries=[],
            expected_commands=['MIGRATE'],
        ),
    ],
)
@mock.patch('olympia.amo.management.commands.initialize_data.call_command')
@mock.patch('olympia.amo.management.commands.initialize_data.get_es')
@mock.patch('olympia.amo.management.commands.initialize_data.mysql.connect')
def test_scenarios(
    mock_mysql_connect,
    mock_get_es,
    mock_call_command,
    db_exists,
    index_exists,
    force_db,
    skip_seed,
    skip_index,
    expected_queries,
    expected_commands,
):
    """
    Test the initialize_data command with different scenarios. A scenario defineds:
    - the background state of the application, specifically:
        - 1) if the `olympia` database exists according to mysql
        - 2) if the `addons` index exists according to elasticsearch
    - the arguments passed to the `initialize_data` command

    We can then define what the test expects to happen given these conditions with:
    - the expected ORM operations
    - the expected calls other management commands from the initialize_data command

    Scenarios assume the default background state of a
    totally fresh DB and index with no arguments.

    Thus each set of arguments is defining a specific deviation from the default state
    as well as the exact set of ORM operations and calls to other management commands
    expected from the initialize_data command. Both are asserted in order.

    This test is not exactly simple, but it allows for covering a large set of logic
    to be tested in a systematic way with a large number of configurations.
    """

    # Mock the MySQL connection
    mock_connection = mock.MagicMock()
    mock_mysql_connect.return_value = mock_connection

    # Mock Elasticsearch client
    mock_es = mock.MagicMock()
    mock_get_es.return_value = mock_es

    # Database and index names
    database_name = settings.DATABASES['default']['NAME']

    _queries = {
        'CREATE_DB': f'CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4',
        'DROP_DB': f'DROP DATABASE `{database_name}`',
    }
    _commands = {
        'MIGRATE': [('migrate', '--noinput')],
        'INITIAL_DATA': [
            ('loaddata', 'initial.json'),
            ('import_prod_versions',),
            (
                'createsuperuser',
                '--no-input',
                '--username',
                'local_admin',
                '--email',
                'local_admin@mozilla.com',
            ),
            ('loaddata', 'zadmin/users'),
        ],
        'SEED_DATA': [
            ('reindex', '--wipe', '--force', '--noinput'),
            ('generate_addons', '--app', 'firefox', 10),
            ('generate_addons', '--app', 'android', 10),
            ('generate_themes', 10),
            ('generate_default_addons_for_frontend',),
        ],
        'REINDEX': [('reindex', '--noinput', '--force')],
    }

    if db_exists:
        # Simulate that the database exists
        mock_connection.select_db.return_value = None
        mock_connection.select_db.side_effect = None
    else:
        # Simulate that the database does not exist by raising an exception
        mock_connection.select_db.side_effect = MySQLError('Database does not exist.')

    mock_es.indices.exists.return_value = index_exists

    def _assert_db_queries_executed(query_keys):
        queries = [_queries[key] for key in query_keys]
        executed_queries = [
            call_args.args[0] for call_args in mock_connection.query.call_args_list
        ]

        assert executed_queries == queries, (
            f'Expected queries were not executed in the correct order. '
            f'Expected: {queries}, Actual: {executed_queries}'
        )

    def _assert_commands_called_in_order(command_keys):
        expected_commands = [cmd for key in command_keys for cmd in _commands[key]]
        actual_commands = [
            call_args.args for call_args in mock_call_command.call_args_list
        ]
        assert actual_commands == expected_commands, (
            f'Commands were not called in the expected order. '
            f'Expected: {expected_commands}, Actual: {actual_commands}'
        )

    call_command(
        'initialize_data',
        force_db=force_db,
        skip_seed=skip_seed,
        skip_index=skip_index,
    )

    # Verify DB queries are executed in the correct order
    _assert_db_queries_executed(expected_queries)

    # Verify commands are called in the correct order
    _assert_commands_called_in_order(expected_commands)
