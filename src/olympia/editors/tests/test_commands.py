# -*- coding: utf-8 -*-
import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from olympia import amo
from olympia.addons.models import AddonApprovalsCounter
from olympia.amo.tests import (
    addon_factory, file_factory, TestCase, version_factory)
from olympia.editors.management.commands import auto_approve
from olympia.editors.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary)
from olympia.editors.views import get_reviewing_cache, set_reviewing_cache
from olympia.files.models import FileValidation
from olympia.zadmin.models import Config, get_config, set_config


class TestAutoApproveCommand(TestCase):
    def setUp(self):
        self.addon = addon_factory(average_daily_users=666)
        self.version = version_factory(
            addon=self.addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        self.file = self.version.all_files[0]
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)
        set_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS', 10000)
        set_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES', 1)

        # Always mock log_final_summary() method so we can look at the stats
        # easily.
        patcher = mock.patch.object(auto_approve.Command, 'log_final_summary')
        self.log_final_summary_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _check_stats(self, expected_stats):
        assert self.log_final_summary_mock.call_count == 1
        stats = self.log_final_summary_mock.call_args[0][0]
        assert stats == expected_stats

    def test_handle_no_max_average_daily_users(self):
        # With only one of the 2 keys set, raise CommandError.
        Config.objects.get(
            key='AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS').delete()
        assert get_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS') is None
        with self.assertRaises(CommandError):
            call_command('auto_approve')

        # With both keys set but daily users is 0, raise CommandError.
        set_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS', 0)
        with self.assertRaises(CommandError):
            call_command('auto_approve')

        # With both keys set to non-zero, everything should work.
        set_config('AUTO_APPROVAL_MAX_AVERAGE_DAILY_USERS', 10000)
        call_command('auto_approve')

    def test_handle_no_min_approved_updates(self):
        # With only one of the 2 keys set, raise CommandError.
        Config.objects.get(
            key='AUTO_APPROVAL_MIN_APPROVED_UPDATES').delete()
        assert get_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES') is None
        with self.assertRaises(CommandError):
            call_command('auto_approve')

        # With both keys set but min approved updates is 0, raise CommandError.
        set_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES', 0)
        with self.assertRaises(CommandError):
            call_command('auto_approve')

        # With both keys set to non-zero, everything should work.
        set_config('AUTO_APPROVAL_MIN_APPROVED_UPDATES', 1)
        call_command('auto_approve')

    def test_fetch_candidates(self):
        # Add a bunch of add-ons in various states that should not be returned.
        # Public add-on with no updates.
        addon_factory(file_kw={'is_webextension': True})

        # Non-extension with updates.
        search_addon = addon_factory(type=amo.ADDON_SEARCH)
        version_factory(addon=search_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW,
            'is_webextension': True})

        # Disabled add-on with updates.
        disabled_addon = addon_factory(disabled_by_user=True)
        version_factory(addon=disabled_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW,
            'is_webextension': True})

        # Non-public add-on
        addon_factory(status=amo.STATUS_NOMINATED, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW,
            'is_webextension': True})

        # Add-on with deleted version.
        addon_with_deleted_version = addon_factory()
        deleted_version = version_factory(
            addon=addon_with_deleted_version, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        deleted_version.delete()

        # Add-on with a non-webextension update.
        non_webext_addon = addon_factory()
        version_factory(addon=non_webext_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW})

        # Add-on with 3 versions:
        # - one webext, listed, public.
        # - one non-listed webext version
        # - one listed non-webext awaiting review.
        complex_addon = addon_factory(file_kw={'is_webextension': True})
        version_factory(
            addon=complex_addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'is_webextension': True})
        version_factory(addon=complex_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW})

        # Finally, add a second file to self.version to test the distinct().
        file_factory(
            version=self.version, status=amo.STATUS_AWAITING_REVIEW,
            is_webextension=True)

        # Gather the candidates.
        command = auto_approve.Command()
        qs = command.fetch_candidates()

        # Only self.version should be found, once.
        assert len(qs) == 1
        assert qs[0] == self.version

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_skip_if_admin_review(self, create_summary_for_version_mock):
        self.addon.update(admin_review=True)
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 0
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'flagged': 1})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_skip_if_has_info_request(self, create_summary_for_version_mock):
        self.version.update(has_info_request=True)
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 0
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'flagged': 1})

    def test_full(self):
        # Simple integration test.
        assert not AutoApprovalSummary.objects.exists()
        call_command('auto_approve', '--dry-run')
        call_command('auto_approve')
        assert AutoApprovalSummary.objects.count() == 1
        assert AutoApprovalSummary.objects.get(version=self.version)
        assert get_reviewing_cache(self.addon.pk) is None

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_already_locked(self, create_summary_for_version_mock):
        # Test that when an add-on is locked, we handle that gracefully, not
        # touching it.
        set_reviewing_cache(self.addon.pk, 666)
        call_command('auto_approve')
        assert get_reviewing_cache(self.addon.pk) == 666
        assert create_summary_for_version_mock.call_count == 0
        self._check_stats({'total': 1, 'locked': 1})

    @mock.patch.object(auto_approve, 'set_reviewing_cache')
    @mock.patch.object(auto_approve, 'clear_reviewing_cache')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_locking(
            self, create_summary_for_version_mock, clear_reviewing_cache_mock,
            set_reviewing_cache_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert set_reviewing_cache_mock.call_count == 1
        assert set_reviewing_cache_mock.call_args == (
            (self.addon.pk, settings.TASK_USER_ID), {})
        assert clear_reviewing_cache_mock.call_count == 1
        assert clear_reviewing_cache_mock.call_args == ((self.addon.pk,), {})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_not_enough_files_error(self, create_summary_for_version_mock):
        create_summary_for_version_mock.side_effect = (
            AutoApprovalNotEnoughFilesError)
        call_command('auto_approve')
        assert get_reviewing_cache(self.addon.pk) is None
        assert create_summary_for_version_mock.call_count == 1
        self._check_stats({'total': 1, 'error': 1})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_no_validation_result(self, create_summary_for_version_mock):
        create_summary_for_version_mock.side_effect = (
            AutoApprovalNoValidationResultError)
        call_command('auto_approve')
        assert get_reviewing_cache(self.addon.pk) is None
        assert create_summary_for_version_mock.call_count == 1
        self._check_stats({'total': 1, 'error': 1})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict_dry_run(self, create_summary_for_version_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED), {})
        call_command('auto_approve', '--dry-run')
        assert create_summary_for_version_mock.call_args == (
            (self.version, ),
            {'max_average_daily_users': 10000, 'min_approved_updates': 1,
             'dry_run': True})
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict(self, create_summary_for_version_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.AUTO_APPROVED), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_args == (
            (self.version, ),
            {'max_average_daily_users': 10000, 'min_approved_updates': 1,
             'dry_run': False})
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_failed_verdict(self, create_summary_for_version_mock):
        fake_verdict_info = {
            'uses_custom_csp': True,
            'uses_native_messaging': True,
            'uses_content_script_for_all_urls': True,
            'too_many_average_daily_users': True,
            'too_few_approved_updates': True,
        }
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.NOT_AUTO_APPROVED),
            fake_verdict_info)
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_args == (
            (self.version, ),
            {'max_average_daily_users': 10000, 'min_approved_updates': 1,
             'dry_run': False})
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({
            'total': 1,
            'uses_custom_csp': 1,
            'uses_native_messaging': 1,
            'uses_content_script_for_all_urls': 1,
            'too_many_average_daily_users': 1,
            'too_few_approved_updates': 1,
        })
