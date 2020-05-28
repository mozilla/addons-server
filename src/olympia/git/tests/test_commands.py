import datetime

from pathlib import Path
from unittest import mock

import pytest

from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_switch,
    version_factory,
)
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

from .test_utils import update_git_repo_creation_time


class TestGitExtraction(TestCase):
    def setUp(self):
        super().setUp()

        self.command = GitExtractionCommand()
        self.addon = addon_factory(
            file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
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
        e3 = GitExtractionEntry.objects.create(
            addon=addon_factory(file_kw={'is_webextension': True})
        )
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
        e3 = GitExtractionEntry.objects.create(
            addon=addon_factory(file_kw={'is_webextension': True})
        )
        e4 = GitExtractionEntry.objects.create(
            addon=addon_factory(file_kw={'is_webextension': True})
        )
        self.command.extract_addon = mock.Mock()

        self.command.handle(None, limit=2)

        self.command.extract_addon.assert_has_calls(
            [mock.call(e4), mock.call(e3)]
        )
        assert self.command.extract_addon.call_count == 2

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_aborts_when_addon_is_already_being_extracted(
        self, chain_mock
    ):
        entry = GitExtractionEntry.objects.create(
            addon=self.addon, in_progress=True
        )

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
            addon=self.addon, file_kw={'is_webextension': True}
        )
        version_deleted = version_factory(
            addon=self.addon, deleted=True, file_kw={'is_webextension': True}
        )
        # This version should be ignored because it is not a web-extension.
        version_factory(addon=self.addon, file_kw={'is_webextension': False})
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
            addon=self.addon, file_kw={'is_webextension': True}
        )
        version_factory(addon=self.addon, file_kw={'is_webextension': True})
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        self.command.extract_addon(entry, batch_size=2)

        chain_mock.assert_called_with(
            extract_versions_to_git.si(
                addon_pk=self.addon.pk, version_pks=[version1.pk, version2.pk]
            ),
            continue_git_extraction.si(self.addon.pk),
        )

    @mock.patch('olympia.git.management.commands.git_extraction.chain')
    def test_extract_addon_remove_entry_immediately_when_no_version(
        self, chain_mock
    ):
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
        # This version should be ignored because it is not a web-extension.
        skipped_version = version_factory(
            addon=self.addon, file_kw={'is_webextension': False}
        )
        version_2 = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            },
        )
        repo = AddonGitRepository(self.addon)
        entry = GitExtractionEntry.objects.create(addon=self.addon)

        assert not version_1.git_hash
        assert not version_2.git_hash
        assert not repo.is_extracted
        assert not skipped_version.git_hash

        # First execution of the CRON task.
        self.command.extract_addon(entry, batch_size=1)
        version_1.refresh_from_db()
        version_2.refresh_from_db()
        skipped_version.refresh_from_db()
        entry.refresh_from_db()

        assert repo.is_extracted
        assert version_1.git_hash
        # We only git-extracted the first version because of batch_size=1.
        assert not version_2.git_hash
        # We keep the entry and we set `in_progress` to `False` because we
        # still need to extract the second version.
        assert not entry.in_progress
        assert GitExtractionEntry.objects.filter(pk=entry.pk).exists()
        assert not skipped_version.git_hash

        # Second execution of the CRON task.
        self.command.extract_addon(entry, batch_size=1)
        version_2.refresh_from_db()
        skipped_version.refresh_from_db()

        assert repo.is_extracted
        assert version_2.git_hash
        assert not GitExtractionEntry.objects.filter(pk=entry.pk).exists()
        assert not skipped_version.git_hash

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
