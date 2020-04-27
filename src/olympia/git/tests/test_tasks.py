from unittest import mock

from olympia.amo.tests import TestCase, addon_factory

from olympia.git.models import GitExtractionEntry
from olympia.git.tasks import (
    remove_git_extraction_entry,
    on_extraction_error,
    extract_versions_to_git,
)
from olympia.lib.git import AddonGitRepository, BrokenRefError


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
        assert addon_repo.is_extracted
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
