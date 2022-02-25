import datetime
import io
import os

from pathlib import Path
from unittest import mock

import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_switch,
    version_factory,
)
from olympia.files.utils import id_to_path
from olympia.git.utils import AddonGitRepository, BrokenRefError
from olympia.git.models import GitExtractionEntry
from olympia.git.tasks import (
    continue_git_extraction,
    extract_versions_to_git,
    remove_git_extraction_entry,
)

from olympia.git.management.commands.git_extraction import (
    SWITCH_NAME,
    Command as GitExtractionCommand,
)
from olympia.git.management.commands.migrate_git_storage_to_new_structure import (
    Command as MigrateGitStorageToNewStructureCommand,
)

from .test_utils import update_git_repo_creation_time


class TestGitExtraction(TestCase):
    def setUp(self):
        super().setUp()

        self.command = GitExtractionCommand()
        self.addon = addon_factory(
            file_kw={
                'filename': 'webextension_no_id.xpi',
            }
        )

    @mock.patch('olympia.git.management.commands.git_extraction.lock')
    def test_handle_does_not_run_if_switch_is_not_active(self, lock_mock):
        create_switch(SWITCH_NAME, active=False)

        self.command.handle()

        lock_mock.assert_not_called()

    @mock.patch('olympia.git.management.commands.git_extraction.lock')
    def test_handle_tries_to_acquire_lock(self, lock_mock):
        create_switch(SWITCH_NAME, active=True)

        self.command.handle()

        lock_mock.assert_called()

    def test_handle_calls_extract_addon_for_each_addon_in_queue(self):
        create_switch(SWITCH_NAME, active=True)
        e1 = GitExtractionEntry.objects.create(addon=self.addon)
        # Create a duplicate add-on.
        e2 = GitExtractionEntry.objects.create(addon=self.addon)
        # Create another add-on.
        e3 = GitExtractionEntry.objects.create(addon=addon_factory())
        self.command.extract_addon = mock.Mock()

        self.command.handle()

        self.command.extract_addon.assert_has_calls(
            [mock.call(e3), mock.call(e2), mock.call(e1)]
        )
        assert self.command.extract_addon.call_count == 3

    def test_handle_limits_the_number_of_entries_to_process(self):
        create_switch(SWITCH_NAME, active=True)
        GitExtractionEntry.objects.create(addon=self.addon)
        # Create a duplicate add-on.
        GitExtractionEntry.objects.create(addon=self.addon)
        # Create another add-on.
        e3 = GitExtractionEntry.objects.create(addon=addon_factory())
        e4 = GitExtractionEntry.objects.create(addon=addon_factory())
        self.command.extract_addon = mock.Mock()

        self.command.handle(None, limit=2)

        self.command.extract_addon.assert_has_calls([mock.call(e4), mock.call(e3)])
        assert self.command.extract_addon.call_count == 2

    def test_handle_entries_with_same_created_date(self):
        create_switch(SWITCH_NAME, active=True)
        created = datetime.datetime(2020, 7, 5)
        # First entry inserted for the add-on.
        GitExtractionEntry.objects.create(addon=self.addon, created=created)
        # Second entry inserted for the add-on.
        GitExtractionEntry.objects.create(addon=self.addon, created=created)
        # Third entry inserted for the add-on but this one has
        # `in_progress=False` to simulate a previous execution of the task.
        # Without the right `order` value, other entries might be processed
        # instead of this one.
        e1_3 = GitExtractionEntry.objects.create(
            addon=self.addon, created=created, in_progress=False
        )
        self.command.extract_addon = mock.Mock()

        self.command.handle(None, limit=2)

        self.command.extract_addon.assert_has_calls(
            [mock.call(e1_3), mock.call(mock.ANY)]
        )
        assert self.command.extract_addon.call_count == 2

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_aborts_when_addon_is_already_being_extracted(
        self, chain_mock
    ):
        entry = GitExtractionEntry.objects.create(addon=self.addon, in_progress=True)

        self.command.extract_addon(entry)

        chain_mock.assert_not_called()
        assert GitExtractionEntry.objects.filter(pk=entry.pk).exists()

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_with_mock(self, chain_mock):
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry)

        chain_mock.assert_called_with(
            extract_versions_to_git.si(
                addon_pk=self.addon.pk,
                version_pks=[self.addon.current_version.pk],
            ),
            remove_git_extraction_entry.si(self.addon.pk),
        )

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_called_more_than_once(self, chain_mock):
        entry1 = GitExtractionEntry.objects.create(addon=self.addon)
        entry2 = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry1)
        self.command.extract_addon(entry2)

        chain_mock.assert_called_with(
            extract_versions_to_git.si(
                addon_pk=self.addon.pk,
                version_pks=[self.addon.current_version.pk],
            ),
            remove_git_extraction_entry.si(self.addon.pk),
        )
        chain_mock.call_count == 1

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_with_multiple_versions(self, chain_mock):
        version1 = self.addon.current_version
        version2 = version_factory(
            addon=self.addon,
        )
        version_deleted = version_factory(
            addon=self.addon,
            deleted=True,
        )
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry)

        chain_mock.assert_called_with(
            extract_versions_to_git.si(
                addon_pk=self.addon.pk,
                version_pks=[version1.pk, version2.pk, version_deleted.pk],
            ),
            remove_git_extraction_entry.si(self.addon.pk),
        )

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_continues_git_extraction(self, chain_mock):
        version1 = self.addon.current_version
        version2 = version_factory(
            addon=self.addon,
        )
        version_factory(
            addon=self.addon,
        )
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry, batch_size=2)

        chain_mock.assert_called_with(
            extract_versions_to_git.si(
                addon_pk=self.addon.pk, version_pks=[version1.pk, version2.pk]
            ),
            continue_git_extraction.si(self.addon.pk),
        )

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_remove_entry_immediately_when_no_version(self, chain_mock):
        self.addon.current_version.update(git_hash='some hash')
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry)

        chain_mock.assert_not_called()
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_remove_entry_immediately_when_not_extension(
        self, chain_mock
    ):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry)

        chain_mock.assert_not_called()
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()

    def test_extract_addon(self):
        version = self.addon.current_version
        repo = AddonGitRepository(self.addon)
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        assert not version.git_hash
        assert not repo.is_extracted

        self.command.extract_addon(entry)
        version.refresh_from_db()

        assert repo.is_extracted
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()
        assert version.git_hash

    def test_extract_addon_with_more_versions_than_batch_size(self):
        version_1 = self.addon.current_version
        version_2 = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )
        repo = AddonGitRepository(self.addon)
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        assert not version_1.git_hash
        assert not version_2.git_hash
        assert not repo.is_extracted

        # First execution of the CRON task.
        self.command.extract_addon(entry, batch_size=1)
        version_1.refresh_from_db()
        version_2.refresh_from_db()
        entry.refresh_from_db()

        assert repo.is_extracted
        assert version_1.git_hash
        # We only git-extracted the first version because of batch_size=1.
        assert not version_2.git_hash
        # We keep the entry and we set `in_progress` to `False` because we
        # still need to extract the second version.
        assert not entry.in_progress
        assert GitExtractionEntry.objects.filter(pk=entry.pk).exists()

        # Second execution of the CRON task.
        self.command.extract_addon(entry, batch_size=1)
        version_2.refresh_from_db()

        assert repo.is_extracted
        assert version_2.git_hash
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()

    # Overriding this setting is needed to tell Celery to run the error handler
    # (because we run Celery in eager mode in the test env). That being said,
    # Celery still raises errors so... we have to catch the exception too.
    @override_settings(CELERY_TASK_EAGER_PROPAGATES=False)
    def test_extract_addon_with_broken_ref_error_during_extraction(self):
        version = self.addon.current_version
        repo = AddonGitRepository(self.addon)
        # Force the creation of the git repository.
        repo.git_repository
        assert repo.is_extracted
        # Set the "creation time" of the git repository to something older than
        # 1 hour.
        update_git_repo_creation_time(repo, time=datetime.datetime(2020, 1, 1))
        # Create a broken ref, see:
        # https://github.com/mozilla/addons-server/issues/13590
        Path(f'{repo.git_repository_path}/.git/refs/heads/listed').touch()
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        with pytest.raises(BrokenRefError):
            self.command.extract_addon(entry)

        version.refresh_from_db()

        assert not repo.is_extracted
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()
        assert not version.git_hash
        new_entry = GitExtractionEntry.objects.get(addon_id=self.addon.pk)
        assert new_entry and new_entry.in_progress is None


class TestMigrateGitStorageToNewStructure(TestCase):
    def setUp(self):
        super().setUp()

        self.command = MigrateGitStorageToNewStructureCommand()
        self.command.fake = False
        self.command.print_prefix = ''
        self.command.verbosity = 1
        self.command.stderr = io.StringIO()
        self.command.stdout = io.StringIO()

    def test_get_new_path(self):
        assert self.command.get_new_path(60).endswith(
            'storage/new-git-storage/0/60/60/60'
        )
        assert self.command.get_new_path(623).endswith(
            'storage/new-git-storage/3/23/623/623'
        )
        assert self.command.get_new_path(3452581).endswith(
            'storage/new-git-storage/1/81/581/3452581'
        )

    def test_create_new_directory_structure_fake(self):
        self.command.fake = True
        # Even in fake mode, we create the full new structure (otherwise
        # migrating under fake mode would fail right at the beginning)
        self.test_create_new_directory_structure()

    @mock.patch('os.makedirs')
    def test_create_new_directory_structure(self, makedirs_mock):
        self.command.create_new_directory_structure()
        self.command.stderr.seek(0)
        self.command.stdout.seek(0)
        assert self.command.stderr.read() == ''

        # 10 directories containing 10 directories containing 10 directories...
        # plus one for the special '60' directory for the single < 3 digit
        # addon_id we have...
        assert makedirs_mock.call_count == 1001

        # Same number of writes to stdout
        stdout = self.command.stdout.read().strip('\n').split('\n')
        assert len(stdout) == 1001

        for call in makedirs_mock.call_args_list:
            assert call.kwargs == {'exist_ok': True}

        # Spot check a few of them... The weird path with ../.. is caused by
        # our settings...
        assert (
            makedirs_mock.call_args_list[56]
            .args[0]
            .endswith('storage/new-git-storage/0/50/650')
        )
        assert stdout[56].endswith('storage/new-git-storage/0/50/650')
        assert (
            makedirs_mock.call_args_list[64]
            .args[0]
            .endswith('storage/new-git-storage/0/60/460')
        )
        assert stdout[64].endswith('storage/new-git-storage/0/60/460')
        # The infamous special '60' case, should be after all the other
        # entries under 0/60/.
        assert (
            makedirs_mock.call_args_list[70]
            .args[0]
            .endswith('storage/new-git-storage/0/60/60')
        )
        assert stdout[70].endswith('storage/new-git-storage/0/60/60')

    @mock.patch('os.scandir')
    @mock.patch('os.rename')
    def test_migrate(self, rename_mock, scandir_mock):
        def scandir_side_effect(*args, **kwargs):
            # Return somewhat realistic paths when calling scandir().
            suffix = args[0].rpartition('/')[-1]
            return_value = [
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'4815162342{suffix}',
                    path=os.path.join(args[0], f'4815162342{suffix}'),
                ),
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'123456789{suffix}',
                    path=os.path.join(args[0], f'123456789{suffix}'),
                ),
            ]
            for mocked in return_value:
                mocked.name = (
                    mocked._name
                )  # Ugly but `name` is a special attribute in mocks.
            return return_value

        scandir_mock.side_effect = scandir_side_effect

        self.command.migrate()

        # We should have looked into 10*10 directories
        assert scandir_mock.call_count == 100
        # Spot check a couple calls
        assert (
            scandir_mock.call_args_list[12].args[0].endswith('storage/git-storage/1/21')
        )
        assert (
            scandir_mock.call_args_list[43].args[0].endswith('storage/git-storage/4/34')
        )

        # And since our mock returned 2 entries everytime, we should have
        # 100*2 calls to rename.
        assert rename_mock.call_count == 200
        # Spot check a couple calls.
        assert (
            rename_mock.call_args_list[24]
            .args[0]
            .endswith('storage/git-storage/1/21/481516234221')
        )
        assert (
            rename_mock.call_args_list[24]
            .args[1]
            .endswith('storage/new-git-storage/1/21/221/481516234221')
        )
        assert rename_mock.call_args_list[25].args[0].endswith('1/21/12345678921')
        assert (
            rename_mock.call_args_list[25]
            .args[1]
            .endswith('storage/new-git-storage/1/21/921/12345678921')
        )

    def test_migrate_stdout(self):
        self.test_migrate()
        self.command.stderr.seek(0)
        self.command.stdout.seek(0)
        assert self.command.stderr.read() == ''
        out = self.command.stdout.read().strip('\n').split('\n')
        assert len(out) == 2
        assert out == ['Migrating 12345678994 (n=100)', 'Migrating 12345678999 (n=200)']

    def test_migrate_extra_verbose(self):
        self.command.verbosity = 2
        self.test_migrate()
        self.command.stderr.seek(0)
        self.command.stdout.seek(0)
        assert self.command.stderr.read() == ''
        out = self.command.stdout.read().strip('\n').split('\n')
        assert len(out) == 200

    @mock.patch('os.scandir')
    @mock.patch('os.rename')
    def test_migrate_error(self, rename_mock, scandir_mock):
        # Cause a FileNotFoundError when calling scandir() should be caught,
        # written to stdout and ignored: we just move on to the next directory.
        def scandir_side_effect(*args, **kwargs):
            # Cause a FileNotFound for this path...
            if args[0].endswith('/21'):
                raise FileNotFoundError
            # Return somewhat realistic paths otherwise.
            suffix = args[0].rpartition('/')[-1]
            return_value = [
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'4815162342{suffix}',
                    path=os.path.join(args[0], f'4815162342{suffix}'),
                ),
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'123456789{suffix}',
                    path=os.path.join(args[0], f'123456789{suffix}'),
                ),
            ]
            for mocked in return_value:
                mocked.name = (
                    mocked._name
                )  # Ugly but `name` is a special attribute in mocks.
            return return_value

        scandir_mock.side_effect = scandir_side_effect

        self.command.migrate()

        # We should have looked into 10*10 directories
        assert scandir_mock.call_count == 100
        # Spot check a couple calls
        assert (
            scandir_mock.call_args_list[12].args[0].endswith('storage/git-storage/1/21')
        )
        assert (
            scandir_mock.call_args_list[43].args[0].endswith('storage/git-storage/4/34')
        )

        # And since our mock returned 2 entries everytime, and we raised an error for
        # a single path, we should have (100-1)*2 calls to rename - skiping the broken
        # path and its 2 entries.
        assert rename_mock.call_count == 198
        # Spot check a couple calls. The side effect caused /21 to be skipped, otherwise
        # that's what we'd get here instead of /31 (see test above this one).
        assert (
            rename_mock.call_args_list[24]
            .args[0]
            .endswith('storage/git-storage/1/31/481516234231')
        )
        assert (
            rename_mock.call_args_list[24]
            .args[1]
            .endswith('storage/new-git-storage/1/31/231/481516234231')
        )
        assert rename_mock.call_args_list[25].args[0].endswith('1/31/12345678931')
        assert (
            rename_mock.call_args_list[25]
            .args[1]
            .endswith('storage/new-git-storage/1/31/931/12345678931')
        )

    @mock.patch('os.scandir')
    @mock.patch('os.rename')
    def test_migrate_fake(self, rename_mock, scandir_mock):
        self.command.fake = True
        # Should do the scandir() but not the rename()...

        def scandir_side_effect(*args, **kwargs):
            # Return somewhat realistic paths when calling scandir().
            suffix = args[0].rpartition('/')[-1]
            return_value = [
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'4815162342{suffix}',
                    path=os.path.join(args[0], f'4815162342{suffix}'),
                ),
                mock.Mock(
                    spec=os.DirEntry,
                    _name=f'123456789{suffix}',
                    path=os.path.join(args[0], f'123456789{suffix}'),
                ),
            ]
            for mocked in return_value:
                mocked.name = (
                    mocked._name
                )  # Ugly but `name` is a special attribute in mocks.
            return return_value

        scandir_mock.side_effect = scandir_side_effect

        self.command.migrate()

        # We should have looked into 10*10 directories
        assert scandir_mock.call_count == 100
        # Spot check a couple calls
        assert (
            scandir_mock.call_args_list[12].args[0].endswith('storage/git-storage/1/21')
        )
        assert (
            scandir_mock.call_args_list[43].args[0].endswith('storage/git-storage/4/34')
        )

        # No renames since we're in fake mode
        assert rename_mock.call_count == 0

    @mock.patch('os.rename')
    def test_rename_top_directory(self, rename_mock):
        self.command.rename_top_directory()
        assert rename_mock.call_count == 2
        self.command.stdout.seek(0)
        out = self.command.stdout.read().strip('\n').split('\n')
        assert len(out) == 2
        expected_new_temporary_git_storage = os.path.join(
            settings.STORAGE_ROOT, 'new-git-storage'
        )
        expected_old_temporary_git_storage = os.path.join(
            settings.STORAGE_ROOT, 'old-git-storage'
        )
        assert (
            f'{settings.GIT_FILE_STORAGE_PATH} -> {expected_old_temporary_git_storage}'
            in out[0]
        )
        assert (
            f'{expected_new_temporary_git_storage} -> {settings.GIT_FILE_STORAGE_PATH}'
            in out[1]
        )
        assert rename_mock.call_count == 2
        assert rename_mock.call_args_list[0].args[0] == settings.GIT_FILE_STORAGE_PATH
        assert (
            rename_mock.call_args_list[0].args[1] == expected_old_temporary_git_storage
        )
        assert (
            rename_mock.call_args_list[1].args[0] == expected_new_temporary_git_storage
        )
        assert rename_mock.call_args_list[1].args[1] == settings.GIT_FILE_STORAGE_PATH

    @mock.patch('os.rename')
    def test_rename_top_directory_fake(self, rename_mock):
        self.command.fake = True
        self.command.rename_top_directory()
        assert rename_mock.call_count == 0
        self.command.stdout.seek(0)
        out = self.command.stdout.read().strip('\n').split('\n')
        assert len(out) == 2
        assert rename_mock.call_count == 0

    def _create_old_directory_structure(self):
        for addon_id in range(1000, 2001):
            # Pretend we have a bunch of add-ons in the 1000 -> 2001 id range.
            path = os.path.join(
                settings.GIT_FILE_STORAGE_PATH, id_to_path(addon_id, depth=2), 'addon'
            )
            os.makedirs(path)

    def test_full_run(self):
        self._create_old_directory_structure()
        assert os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        assert not os.path.exists(
            os.path.join(
                settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789', 'addon'
            )
        )
        stdout = io.StringIO()
        call_command('migrate_git_storage_to_new_structure', stdout=stdout)
        assert len(os.listdir(settings.GIT_FILE_STORAGE_PATH)) == 10
        assert len(os.listdir(os.path.join(settings.GIT_FILE_STORAGE_PATH, '1'))) == 10
        assert (
            len(os.listdir(os.path.join(settings.GIT_FILE_STORAGE_PATH, '1', '21')))
            == 10
        )
        assert not os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        assert os.path.exists(
            os.path.join(
                settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789', 'addon'
            )
        )
        # new/old temporary paths shouldn't have been left behind.
        assert not os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'new-git-storage', '9', '89', '789')
        )
        assert not os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'old-git-storage', '9', '89', '1789')
        )
        stdout.seek(0)
        assert stdout.read()

    def test_full_run_fake(self):
        self._create_old_directory_structure()
        assert os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        assert not os.path.exists(
            os.path.join(
                settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789', 'addon'
            )
        )
        stdout = io.StringIO()
        call_command('migrate_git_storage_to_new_structure', '--fake', stdout=stdout)
        # Nothing should have been migrated...
        assert os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        # New directory structure in temporary new storage path *should* have been
        # created though, because it's needed to proceed.
        assert os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'new-git-storage', '9', '89', '789')
        )
        # We just shouldn't have used it to store anything (1789 is an add-on id).
        assert not os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789')
        )
        stdout.seek(0)
        assert stdout.read()

    def test_full_run_dont_migrate(self):
        self._create_old_directory_structure()
        assert os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        assert not os.path.exists(
            os.path.join(
                settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789', 'addon'
            )
        )
        stdout = io.StringIO()
        call_command(
            'migrate_git_storage_to_new_structure', '--dont-migrate', stdout=stdout
        )
        # Nothing should have been migrated...
        assert os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        assert not os.path.exists(
            os.path.join(
                settings.GIT_FILE_STORAGE_PATH, '9', '89', '789', '1789', 'addon'
            )
        )
        # But new directories should have been created in the temporary new directory.
        assert os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'new-git-storage', '9', '89', '789')
        )
        stdout.seek(0)
        assert stdout.read()

    def test_full_run_dont_rename_root(self):
        self._create_old_directory_structure()
        stdout = io.StringIO()
        call_command(
            'migrate_git_storage_to_new_structure', '--dont-rename-root', stdout=stdout
        )
        # We should have migrated add-ons to new temporary path, without having renamed
        # that temporary path to the final one.
        assert os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'new-git-storage', '9', '89', '789')
        )
        assert os.path.exists(
            os.path.join(
                settings.STORAGE_ROOT,
                'new-git-storage',
                '9',
                '89',
                '789',
                '1789',
                'addon',
            )
        )
        assert not os.path.exists(
            os.path.join(settings.GIT_FILE_STORAGE_PATH, '9', '89', '1789', 'addon')
        )
        # Temporary path with the old structure shouldn't have been created.
        assert not os.path.exists(
            os.path.join(settings.STORAGE_ROOT, 'old-git-storage')
        )
        stdout.seek(0)
        assert stdout.read()

    def test_full_run_temporary_old_git_file_storage_path_exists(self):
        expected_old_temporary_git_storage = os.path.join(
            settings.STORAGE_ROOT, 'old-git-storage'
        )
        os.mkdir(expected_old_temporary_git_storage)
        with self.assertRaises(CommandError):
            call_command('migrate_git_storage_to_new_structure')
