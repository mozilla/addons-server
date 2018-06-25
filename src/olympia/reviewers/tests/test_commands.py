# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.management import call_command

import mock

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.utils import ACTIVITY_MAIL_GROUP
from olympia.addons.models import (
    AddonApprovalsCounter, AddonReviewerFlags, AddonUser)
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, user_factory, version_factory)
from olympia.files.models import FileValidation
from olympia.files.utils import atomic_lock
from olympia.reviewers.management.commands import auto_approve
from olympia.reviewers.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, ReviewerScore, get_reviewing_cache)


class TestAutoApproveCommand(TestCase):
    def setUp(self):
        self.user = user_factory(
            id=settings.TASK_USER_ID, username='taskuser',
            email='taskuser@mozilla.com')
        self.addon = addon_factory(average_daily_users=666)
        self.version = version_factory(
            addon=self.addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        self.file = self.version.all_files[0]
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

        # Always mock log_final_summary() method so we can look at the stats
        # easily.
        patcher = mock.patch.object(auto_approve.Command, 'log_final_summary')
        self.log_final_summary_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _check_stats(self, expected_stats):
        # We abuse the fact that log_final_summary receives stats as positional
        # argument to check what happened.
        assert self.log_final_summary_mock.call_count == 1
        stats = self.log_final_summary_mock.call_args[0][0]
        assert stats == expected_stats

    def test_fetch_candidates(self):
        # We already have an add-on with a version awaiting review that should
        # be considered. Make sure its nomination date is in the past to test
        # ordering.
        self.version.update(nomination=self.days_ago(1))
        # Add reviewer flags disabling auto-approval for this add-on. It would
        # still be fetched as a candidate, just rejected later on when
        # calculating the verdict.
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled=True)

        # Add nominated add-on: it should be considered.
        new_addon = addon_factory(status=amo.STATUS_NOMINATED, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW,
            'is_webextension': True})
        new_addon_version = new_addon.versions.all()[0]
        new_addon_version.update(nomination=self.days_ago(2))
        # Even add an empty reviewer flags instance, that should not matter.
        AddonReviewerFlags.objects.create(addon=new_addon)

        # Add langpack: it should also be considered.
        langpack = addon_factory(
            type=amo.ADDON_LPAPP, status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        langpack_version = langpack.versions.all()[0]
        langpack_version.update(nomination=self.days_ago(3))

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
        command.post_review = True
        qs = command.fetch_candidates()

        # 3 versions should be found. Because of the nomination date,
        # langpack_version should be first (its nomination date is the oldest),
        # followed by new_addon_version and then self.version.
        assert len(qs) == 3
        assert qs[0] == langpack_version
        assert qs[1] == new_addon_version
        assert qs[2] == self.version

    @mock.patch(
        'olympia.reviewers.management.commands.auto_approve.statsd.incr')
    @mock.patch(
        'olympia.reviewers.management.commands.auto_approve.ReviewHelper')
    def test_approve(self, review_helper_mock, statsd_incr_mock):
        command = auto_approve.Command()
        command.approve(self.version)
        assert review_helper_mock.call_count == 1
        assert review_helper_mock.call_args == (
            (), {'addon': self.addon, 'version': self.version}
        )
        assert review_helper_mock().handler.process_public.call_count == 1
        assert statsd_incr_mock.call_count == 1
        assert statsd_incr_mock.call_args == (
            ('reviewers.auto_approve.approve',), {}
        )

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_full(self, sign_file_mock):
        # Simple integration test with as few mocks as possible.
        assert not AutoApprovalSummary.objects.exists()
        assert not self.file.reviewed
        ActivityLog.objects.all().delete()
        self.author = user_factory()
        self.addon.addonuser_set.create(user=self.author)

        # Delete the add-on current version and approval info, leaving it
        # nominated. Because we're in post-review we should pick it up and
        # approve it anyway.
        AddonApprovalsCounter.objects.filter(addon=self.addon).get().delete()
        self.addon.current_version.delete()
        self.addon.update_status()

        call_command('auto_approve', '--dry-run')
        call_command('auto_approve')

        self.addon.reload()
        self.file.reload()
        assert AutoApprovalSummary.objects.count() == 1
        assert AutoApprovalSummary.objects.get(version=self.version)
        assert get_reviewing_cache(self.addon.pk) is None
        assert self.addon.status == amo.STATUS_PUBLIC
        assert self.file.status == amo.STATUS_PUBLIC
        assert self.file.reviewed
        assert ActivityLog.objects.count()
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.APPROVE_VERSION.id
        assert sign_file_mock.call_count == 1
        assert sign_file_mock.call_args[0][0] == self.file
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == [self.author.email]
        assert msg.from_email == settings.ADDONS_EMAIL
        assert msg.subject == 'Mozilla Add-ons: %s %s Approved' % (
            unicode(self.addon.name), self.version.version)

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

    @mock.patch.object(auto_approve, 'set_reviewing_cache')
    @mock.patch.object(auto_approve, 'clear_reviewing_cache')
    @mock.patch.object(AutoApprovalSummary, 'check_is_locked')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_no_locking_if_already_locked(
            self, create_summary_for_version_mock, check_is_locked_mock,
            clear_reviewing_cache_mock, set_reviewing_cache_mock):
        check_is_locked_mock.return_value = True
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert set_reviewing_cache_mock.call_count == 0
        assert clear_reviewing_cache_mock.call_count == 0

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

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict_dry_run(
            self, create_summary_for_version_mock, approve_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED), {})
        call_command('auto_approve', '--dry-run')
        assert approve_mock.call_count == 0
        assert create_summary_for_version_mock.call_args == (
            (self.version, ), {'dry_run': True})
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict(
            self, create_summary_for_version_mock, approve_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.AUTO_APPROVED), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert create_summary_for_version_mock.call_args == (
            (self.version, ), {'dry_run': False})
        assert get_reviewing_cache(self.addon.pk) is None
        assert approve_mock.call_count == 1
        assert approve_mock.call_args == (
            (self.version, ), {})
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_failed_verdict(
            self, create_summary_for_version_mock, approve_mock):
        fake_verdict_info = {
            'is_locked': True
        }
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.NOT_AUTO_APPROVED),
            fake_verdict_info)
        call_command('auto_approve')
        assert approve_mock.call_count == 0
        assert create_summary_for_version_mock.call_args == (
            (self.version, ), {'dry_run': False})
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({
            'total': 1,
            'is_locked': 1,
        })

    def test_prevent_multiple_runs_in_parallel(self):
        # Create a lock manually, the command should exit immediately without
        # doing anything.
        with atomic_lock(settings.TMP_PATH, auto_approve.LOCK_NAME):
            call_command('auto_approve')

        assert self.log_final_summary_mock.call_count == 0
        assert self.file.reload().status == amo.STATUS_AWAITING_REVIEW


class TestAwardPostReviewPoints(TestCase):
    def setUp(self):
        self.user1 = user_factory()
        self.user2 = user_factory()
        self.user3 = user_factory()
        self.addon1 = addon_factory()
        self.addon2 = addon_factory()
        # First user approved content of addon1.
        ActivityLog.create(
            amo.LOG.APPROVE_CONTENT, self.addon1,
            self.addon1.current_version, user=self.user1)
        # Second user confirmed auto-approved of addon2.
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, self.addon2,
            self.addon2.current_version, user=self.user2)
        # Third user approved content of addon2.
        ActivityLog.create(
            amo.LOG.APPROVE_CONTENT, self.addon2,
            self.addon2.current_version, user=self.user3,)

    def test_missing_auto_approval_summary(self):
        assert ReviewerScore.objects.count() == 0
        call_command('award_post_review_points')
        # CONFIRM_AUTO_APPROVED was skipped since we can't determine its
        # weight (has no AutoApprovalSummary).
        assert ReviewerScore.objects.count() == 2
        first_score = ReviewerScore.objects.filter(user=self.user1).get()
        assert first_score.addon == self.addon1
        assert first_score.note == (
            'Retroactively awarded for past post/content review approval.')
        assert first_score.note_key == amo.REVIEWED_CONTENT_REVIEW

        second_score = ReviewerScore.objects.filter(user=self.user3).get()
        assert second_score.addon == self.addon2
        assert second_score.note == (
            'Retroactively awarded for past post/content review approval.')
        assert second_score.note_key == amo.REVIEWED_CONTENT_REVIEW

    def test_full(self):
        AutoApprovalSummary.objects.create(
            version=self.addon2.current_version, verdict=amo.AUTO_APPROVED,
            weight=151, confirmed=True)
        assert ReviewerScore.objects.count() == 0
        call_command('award_post_review_points')
        assert ReviewerScore.objects.count() == 3
        first_score = ReviewerScore.objects.filter(user=self.user1).get()
        assert first_score.addon == self.addon1
        assert first_score.note == (
            'Retroactively awarded for past post/content review approval.')
        assert first_score.note_key == amo.REVIEWED_CONTENT_REVIEW

        second_score = ReviewerScore.objects.filter(user=self.user2).get()
        assert second_score.addon == self.addon2
        assert second_score.note == (
            'Retroactively awarded for past post/content review approval.')
        assert second_score.note_key == amo.REVIEWED_EXTENSION_HIGHEST_RISK

        third_score = ReviewerScore.objects.filter(user=self.user3).get()
        assert third_score.addon == self.addon2
        assert third_score.note == (
            'Retroactively awarded for past post/content review approval.')
        assert third_score.note_key == amo.REVIEWED_CONTENT_REVIEW

    def test_run_twice(self):
        # Running twice should only generate the scores once.
        AutoApprovalSummary.objects.create(
            version=self.addon2.current_version, verdict=amo.AUTO_APPROVED,
            weight=151, confirmed=True)
        call_command('award_post_review_points')
        call_command('award_post_review_points')
        assert ReviewerScore.objects.count() == 3


class TestRecalculatePostReviewWeightsCommand(TestCase):
    @mock.patch.object(AutoApprovalSummary, 'calculate_weight')
    def test_ignore_confirmed(self, calculate_weight_mock):
        addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=addon.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        call_command('recalculate_post_review_weights')
        assert calculate_weight_mock.call_count == 0

    @mock.patch.object(AutoApprovalSummary, 'calculate_weight')
    def test_ignore_not_auto_approved(self, calculate_weight_mock):
        addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=addon.current_version,
            verdict=amo.NOT_AUTO_APPROVED, confirmed=False)
        call_command('recalculate_post_review_weights')
        assert calculate_weight_mock.call_count == 0

    def test_dont_save_if_weight_has_not_changed(self):
        addon = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=addon.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=False, weight=500)
        old_modified_date = self.days_ago(42)
        summary.update(modified=old_modified_date)
        call_command('recalculate_post_review_weights')
        summary.reload()
        assert summary.weight == 500  # Because of no validation results found.
        assert summary.modified == old_modified_date

    def test_save_new_weight(self):
        addon = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=addon.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=False, weight=666)
        old_modified_date = self.days_ago(42)
        summary.update(modified=old_modified_date)
        call_command('recalculate_post_review_weights')
        summary.reload()
        assert summary.weight == 500  # Because of no validation results found.
        assert summary.modified != old_modified_date


class TestSendInfoRequestLastWarningNotification(TestCase):
    @mock.patch('olympia.reviewers.management.commands.'
                'send_info_request_last_warning_notifications.'
                'notify_about_activity_log')
    def test_non_expired(self, notify_about_activity_log_mock):
        addon_factory()  # Normal add-on, no pending info request.
        addon_not_expired = addon_factory()
        flags = AddonReviewerFlags.objects.create(
            addon=addon_not_expired,
            pending_info_request=datetime.now() + timedelta(days=1, hours=3))
        call_command('send_info_request_last_warning_notifications')
        assert notify_about_activity_log_mock.call_count == 0
        assert flags.notified_about_expiring_info_request is False

    @mock.patch('olympia.reviewers.management.commands.'
                'send_info_request_last_warning_notifications.'
                'notify_about_activity_log')
    def test_already_notified(self, notify_about_activity_log_mock):
        addon_factory()
        addon_already_notified = addon_factory()
        flags = AddonReviewerFlags.objects.create(
            addon=addon_already_notified,
            pending_info_request=datetime.now() + timedelta(hours=23),
            notified_about_expiring_info_request=True)
        call_command('send_info_request_last_warning_notifications')
        assert notify_about_activity_log_mock.call_count == 0
        assert flags.notified_about_expiring_info_request is True

    def test_normal(self):
        addon = addon_factory()
        author = user_factory(name=u'Authør')
        AddonUser.objects.create(addon=addon, user=author)
        # Add a pending info request expiring soon.
        flags = AddonReviewerFlags.objects.create(
            addon=addon,
            pending_info_request=datetime.now() + timedelta(hours=23),
            notified_about_expiring_info_request=False)
        # Create reviewer and staff users, and create the request for info
        # activity. Neither the reviewer nor the staff user should be cc'ed.
        reviewer = user_factory(name=u'Revièwer')
        self.grant_permission(reviewer, 'Addons:Review')
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, addon, addon.current_version,
            user=reviewer, details={'comments': u'Fly you fôöls!'})
        staff = user_factory(name=u'Staff Ûser')
        self.grant_permission(staff, 'Some:Perm', name=ACTIVITY_MAIL_GROUP)

        # Fire the command.
        call_command('send_info_request_last_warning_notifications')

        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == [author.email]
        assert msg.subject == u'Mozilla Add-ons: Action Required for %s %s' % (
            addon.name, addon.current_version.version)
        assert 'an issue when reviewing ' in msg.body
        assert 'within one (1) day' in msg.body

        flags.reload()
        assert flags.notified_about_expiring_info_request is True
