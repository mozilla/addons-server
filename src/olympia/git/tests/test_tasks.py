import datetime

from unittest import mock

from olympia.amo.tests import TestCase, addon_factory

from olympia.git.models import GitExtractionEntry
from olympia.git.tasks import (
    continue_git_extraction,
    delete_source_git_repositories,
    remove_git_extraction_entry,
    on_extraction_error,
    extract_versions_to_git,
)
from olympia.lib.git import (
    AddonGitRepository,
    BrokenRefError,
    MissingMasterBranchError,
)

from olympia.lib.tests.test_git import update_git_repo_creation_time


class TestRemoveGitExtractionEntry(TestCase):
    def test_remove_lock(self):
        addon = addon_factory()
        GitExtractionEntry.objects.create(addon=addon, in_progress=True)

        remove_git_extraction_entry(addon_pk=addon.pk)

        assert not GitExtractionEntry.objects.filter(addon=addon).exists()

    def test_remove_does_not_create_a_gitextraction_object(self):
        addon = addon_factory()

        remove_git_extraction_entry(addon_pk=addon.pk)

        assert GitExtractionEntry.objects.count() == 0


class TestContinueGitExtraction(TestCase):
    def test_updates_in_progress_field(self):
        addon = addon_factory()
        entry_in_progress = GitExtractionEntry.objects.create(
            addon=addon, in_progress=True
        )
        assert entry_in_progress.in_progress
        # The queue can have more than one entry per add-on but only one can be
        # in progress. This entry shouldn't be changed by the task.
        another_entry = GitExtractionEntry.objects.create(addon=addon)
        assert another_entry.in_progress is None

        continue_git_extraction(addon_pk=addon.pk)
        entry_in_progress.refresh_from_db()
        another_entry.refresh_from_db()

        assert not entry_in_progress.in_progress
        assert another_entry.in_progress is None


class TestOnExtractionError(TestCase):
    @mock.patch('olympia.git.tasks.remove_git_extraction_entry')
    def test_calls_remove_git_extraction_entry(
        self, remove_git_extraction_entry_mock
    ):
        addon_pk = 123

        on_extraction_error(
            request=None, exc=None, traceback=None, addon_pk=addon_pk
        )

        remove_git_extraction_entry_mock.assert_called_with(addon_pk)

    def test_handles_broken_ref_errors(self):
        addon = addon_factory()
        addon_repo = AddonGitRepository(addon)
        # Create the git repo
        addon_repo.git_repository
        update_git_repo_creation_time(
            addon_repo, time=datetime.datetime(2019, 1, 1)
        )
        assert addon_repo.is_extracted
        assert not addon_repo.is_recent
        # Simulate a git extraction in progress.
        GitExtractionEntry.objects.create(addon_id=addon.pk, in_progress=True)
        # This is the error raised by the task that extracts a version.
        exc = BrokenRefError('cannot locate branch error')

        on_extraction_error(
            request=None, exc=exc, traceback=None, addon_pk=addon.pk
        )

        # The task should remove the git repository on BrokenRefError.
        assert not addon_repo.is_extracted
        # The task should remove the existing git extraction entry.
        assert GitExtractionEntry.objects.filter(in_progress=True).count() == 0
        # The task should re-add the add-on to the git extraction queue.
        assert GitExtractionEntry.objects.filter(in_progress=None).count() == 1

    def test_handles_missing_master_branch(self):
        addon = addon_factory()
        addon_repo = AddonGitRepository(addon)
        # Create the git repo
        addon_repo.git_repository
        update_git_repo_creation_time(
            addon_repo, time=datetime.datetime(2019, 1, 1)
        )
        assert addon_repo.is_extracted
        assert not addon_repo.is_recent
        # Simulate a git extraction in progress.
        GitExtractionEntry.objects.create(addon_id=addon.pk, in_progress=True)
        # This is the error raised by the task that extracts a version.
        exc = MissingMasterBranchError('cannot find master branch')

        on_extraction_error(
            request=None, exc=exc, traceback=None, addon_pk=addon.pk
        )

        # The task should remove the git repository on
        # MissingMasterBranchError.
        assert not addon_repo.is_extracted
        # The task should remove the existing git extraction entry.
        assert GitExtractionEntry.objects.filter(in_progress=True).count() == 0
        # The task should re-add the add-on to the git extraction queue.
        assert GitExtractionEntry.objects.filter(in_progress=None).count() == 1

    def test_with_generic_error(self):
        addon = addon_factory()
        addon_repo = AddonGitRepository(addon)
        # Create the git repo
        addon_repo.git_repository
        assert addon_repo.is_extracted
        # Simulate a git extraction in progress.
        GitExtractionEntry.objects.create(addon_id=addon.pk, in_progress=True)
        exc = Exception('some error')

        on_extraction_error(
            request=None, exc=exc, traceback=None, addon_pk=addon.pk
        )

        assert addon_repo.is_extracted
        assert GitExtractionEntry.objects.count() == 0

    def test_checks_creation_time_before_deleting_repo(self):
        addon = addon_factory()
        addon_repo = AddonGitRepository(addon)
        # Create the git repo
        addon_repo.git_repository
        # We do not update the creation time of the git repository here so that
        # it is less than 1 hour (because the git repository was created in
        # this test case).
        assert addon_repo.is_extracted
        assert addon_repo.is_recent
        # Simulate a git extraction in progress.
        GitExtractionEntry.objects.create(addon_id=addon.pk, in_progress=True)
        # This is the error raised by the task that extracts a version.
        exc = MissingMasterBranchError('cannot find master branch')

        on_extraction_error(
            request=None, exc=exc, traceback=None, addon_pk=addon.pk
        )

        # When the creation time of an add-on git repository is too recent (< 1
        # hour ago), then we do not delete the repository because it might be
        # an "extraction loop" problem.
        assert addon_repo.is_extracted
        # The task should remove the existing git extraction entry.
        assert GitExtractionEntry.objects.filter(in_progress=None).count() == 0
        # The task should NOT re-add the add-on to the git extraction queue.
        assert GitExtractionEntry.objects.filter(in_progress=True).count() == 0


class TestExtractVersionsToGit(TestCase):
    @mock.patch('olympia.git.tasks.extract_version_to_git')
    def test_calls_extract_version_to_git_n_times(
        self, extract_version_to_git_mock
    ):
        extract_versions_to_git(addon_pk=123, version_pks=[1, 2, 3])

        extract_version_to_git_mock.assert_has_calls(
            [
                mock.call(version_id=1, force_extraction=True),
                mock.call(version_id=2, force_extraction=True),
                mock.call(version_id=3, force_extraction=True),
            ]
        )


class TestDeleteSourceGitRepositories(TestCase):
    def test_deletes_source_repositories(self):
        addon_ids = [1, 2, 3]

        for addon_id in addon_ids:
            repo = AddonGitRepository(addon_id, 'source')
            # Create the git repo
            repo.git_repository
            assert repo.is_extracted

        delete_source_git_repositories(ids=addon_ids)

        for addon_id in addon_ids:
            repo = AddonGitRepository(addon_id, 'source')
            assert not repo.is_extracted
