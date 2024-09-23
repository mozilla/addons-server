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
from freezegun import freeze_time

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


class TestBaseDataCommand(TestCase):
    class Commands:
        migrate = ('migrate', '--noinput')
        seed_data = ('seed_data',)
        reindex = ('reindex', '--noinput', '--force')

        def load_data(self, name='_init'):
            return ('load_data', f'--name={name}')

    def setUp(self):
        self.commands = self.Commands()

    def _assert_commands_called_in_order(self, mock_call_command, expected_commands):
        actual_commands = [
            call_args.args for call_args in mock_call_command.call_args_list
        ]
        assert actual_commands == expected_commands, (
            f'Commands were not called in the expected order. '
            f'Expected: {expected_commands}, Actual: {actual_commands}'
        )


class TestDumpDataCommand(TestBaseDataCommand):
    def setUp(self):
        patches = (
            ('mock_exists', 'olympia.amo.management.commands.dump_data.os.path.exists'),
            ('mock_rmtree', 'olympia.amo.management.commands.dump_data.shutil.rmtree'),
            (
                'mock_copytree',
                'olympia.amo.management.commands.dump_data.shutil.copytree',
            ),
            ('mock_makedirs', 'olympia.amo.management.commands.dump_data.os.makedirs'),
            (
                'mock_call_command',
                'olympia.amo.management.commands.dump_data.call_command',
            ),
        )
        self.mocks = {}

        for mock_name, mock_path in patches:
            patcher = mock.patch(mock_path)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

    @freeze_time('2023-06-26 11:00:44')
    def test_default_name(self):
        self.mocks['mock_exists'].return_value = False
        call_command('dump_data')
        self.mocks['mock_exists'].assert_called_with(
            os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, '20230626110044'))
        )

    def test_custom_name(self):
        name = 'test'
        self.mocks['mock_exists'].return_value = False
        call_command('dump_data', name=name)
        self.mocks['mock_exists'].assert_called_with(
            os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, name))
        )

    def test_existing_dump_dir_no_force(self):
        self.mocks['mock_exists'].return_value = True

        with pytest.raises(CommandError):
            call_command('dump_data')

    def test_existing_dump_dir_with_force(self):
        self.mocks['mock_exists'].return_value = True
        call_command('dump_data', force=True)
        self.mocks['mock_rmtree'].assert_called_once()

    def test_dumps_data(self):
        name = 'test'
        dump_path = os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, name))
        self.mocks['mock_exists'].return_value = False
        call_command('dump_data', name=name)

        self.mocks['mock_call_command'].assert_called_once_with(
            'dumpdata',
            format='json',
            indent=2,
            output=os.path.join(dump_path, 'data.json'),
        )
        self.mocks['mock_copytree'].assert_called_once_with(
            settings.STORAGE_ROOT, os.path.join(dump_path, 'storage')
        )


class TestLoadDataCommand(TestBaseDataCommand):
    def setUp(self):
        self.data_backup_dir = os.path.abspath(settings.DATA_BACKUP_DIR)
        self.storage_root = os.path.abspath(settings.STORAGE_ROOT)

    def test_missing_name(self):
        with pytest.raises(CommandError):
            call_command('load_data')

    @mock.patch('olympia.amo.management.commands.load_data.call_command')
    @mock.patch('olympia.amo.management.commands.load_data.shutil.copytree')
    @mock.patch('olympia.amo.management.commands.load_data.os.path.exists')
    def test_custom_name(self, mock_exists, mock_copytree, mock_call_command):
        mock_exists.return_value = True
        custom_name = 'custom_backup'
        call_command('load_data', name=custom_name)
        mock_call_command.assert_called_with(
            'loaddata', os.path.join(self.data_backup_dir, custom_name, 'data.json')
        )
        mock_copytree.assert_called_with(
            os.path.join(self.data_backup_dir, custom_name, 'storage'),
            self.storage_root,
            dirs_exist_ok=True,
        )

    @mock.patch('olympia.amo.management.commands.load_data.call_command')
    @mock.patch('olympia.amo.management.commands.load_data.shutil.copytree')
    @mock.patch('olympia.amo.management.commands.load_data.os.path.exists')
    def test_loaddata_called_with_correct_args(
        self, mock_exists, mock_copytree, mock_call_command
    ):
        mock_exists.return_value = True
        name = 'test_backup'
        call_command('load_data', name=name)
        data_file = os.path.join(self.data_backup_dir, name, 'data.json')
        mock_call_command.assert_called_with('loaddata', data_file)

    @mock.patch('olympia.amo.management.commands.load_data.call_command')
    @mock.patch('olympia.amo.management.commands.load_data.shutil.copytree')
    @mock.patch('olympia.amo.management.commands.load_data.os.path.exists')
    def test_copytree_called_with_correct_args(
        self, mock_exists, mock_copytree, mock_call_command
    ):
        mock_exists.return_value = True
        name = 'test_backup'
        call_command('load_data', name=name)
        storage_from = os.path.join(self.data_backup_dir, name, 'storage')
        storage_to = os.path.abspath(settings.STORAGE_ROOT)
        mock_copytree.assert_called_with(storage_from, storage_to, dirs_exist_ok=True)

    def test_load_data_with_missing_json_file(self):
        pass

    def test_load_data_with_missing_storage_dir(self):
        pass


class TestSeedDataCommand(TestBaseDataCommand):
    @mock.patch('olympia.amo.management.commands.seed_data.call_command')
    @mock.patch('olympia.amo.management.commands.seed_data.shutil.rmtree')
    def test_handle_seed_data(self, mock_rmtree, mock_call_command):
        init_name = settings.DATA_BACKUP_INIT
        init_path = os.path.abspath(os.path.join(settings.DATA_BACKUP_DIR, init_name))

        call_command('seed_data')

        mock_rmtree.assert_called_with(init_path, ignore_errors=True)
        expected_calls = [
            mock.call('flush', '--noinput'),
            mock.call('migrate', '--noinput'),
            mock.call('reindex', '--wipe', '--force', '--noinput'),
            mock.call('loaddata', 'initial.json'),
            mock.call('import_prod_versions'),
            mock.call(
                'createsuperuser',
                '--no-input',
                '--username',
                'local_admin',
                '--email',
                'local_admin@mozilla.com',
            ),
            mock.call('loaddata', 'zadmin/users'),
            mock.call('generate_addons', '--app', 'firefox', 10),
            mock.call('generate_addons', '--app', 'android', 10),
            mock.call('generate_themes', 5),
            mock.call('generate_default_addons_for_frontend'),
            mock.call('dump_data', '--name', init_name),
        ]
        mock_call_command.assert_has_calls(expected_calls, any_order=False)
