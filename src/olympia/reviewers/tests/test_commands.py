# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test.testcases import TransactionTestCase

import six

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.utils import ACTIVITY_MAIL_GROUP
from olympia.addons.models import (
    AddonApprovalsCounter, AddonReviewerFlags, AddonUser)
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, user_factory, version_factory)
from olympia.amo.utils import days_ago
from olympia.discovery.models import DiscoveryItem
from olympia.files.models import FileValidation
from olympia.files.utils import atomic_lock
from olympia.lib.crypto.signing import SigningError
from olympia.reviewers.management.commands import auto_approve
from olympia.reviewers.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, get_reviewing_cache)


class AutoApproveTestsMixin(object):
    def setUp(self):
        # Always mock log_final_summary() method so we can look at the stats
        # easily.
        patcher = mock.patch.object(auto_approve.Command, 'log_final_summary')
        self.log_final_summary_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _check_stats(self, expected_stats):
        # We abuse the fact that log_final_summary receives stats as positional
        # argument to check what happened. Depends on setUp() patching
        # auto_approve.Command.log_final_summary
        assert self.log_final_summary_mock.call_count == 1
        stats = self.log_final_summary_mock.call_args[0][0]
        assert stats == expected_stats


class TestAutoApproveCommand(AutoApproveTestsMixin, TestCase):
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
        super(TestAutoApproveCommand, self).setUp()

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

        # Add langpack: it should be considered.
        langpack = addon_factory(
            type=amo.ADDON_LPAPP, status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        langpack_version = langpack.versions.all()[0]
        langpack_version.update(nomination=self.days_ago(3))

        # Add a dictionary: it should also be considered.
        dictionary = addon_factory(
            type=amo.ADDON_DICT, status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        dictionary_version = dictionary.versions.all()[0]
        dictionary_version.update(nomination=self.days_ago(4))

        # search engine plugins are considered now
        search_addon = addon_factory(type=amo.ADDON_SEARCH)
        version_factory(
            addon=search_addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True},
            nomination=self.days_ago(5))

        # Some recommended add-ons - one nominated and one update.
        # They should be considered by fetch_candidate(), so that they get a
        # weight assigned etc - they will not be auto-approved but that's
        # handled at a later stage, when calculating the verdict.
        recommendable_addon_nominated = addon_factory(
            status=amo.STATUS_NOMINATED,
            version_kw={
                'recommendation_approved': True,
                'nomination': self.days_ago(6)
            },
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True},
        )
        recommended_addon = version_factory(
            addon=addon_factory(),
            recommendation_approved=True,
            nomination=self.days_ago(7),
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True
            }).addon
        DiscoveryItem.objects.create(
            recommendable=True, addon=recommendable_addon_nominated)
        DiscoveryItem.objects.create(
            recommendable=True, addon=recommended_addon)

        # Add a bunch of add-ons in various states that should not be returned.
        # Public add-on with no updates.
        addon_factory(file_kw={'is_webextension': True})

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

        # 5 versions should be found. Because of the nomination date,
        # search_version should be first (its nomination date is the
        # oldest) followed etc.
        assert len(qs) == 7
        assert [v.addon.pk for v in qs] == [a.pk for a in (
            recommended_addon, recommendable_addon_nominated,
            search_addon, dictionary, langpack, new_addon, self.addon,
        )]

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
        # nominated. Set its nomination date in the past and it should be
        # picked up and auto-approved.
        AddonApprovalsCounter.objects.filter(addon=self.addon).get().delete()
        self.addon.current_version.delete()
        self.version.update(nomination=self.days_ago(2))
        self.addon.update_status()

        call_command('auto_approve', '--dry-run')
        call_command('auto_approve')

        self.addon.reload()
        self.file.reload()
        assert AutoApprovalSummary.objects.count() == 1
        assert AutoApprovalSummary.objects.get(version=self.version)
        assert get_reviewing_cache(self.addon.pk) is None
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
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
            six.text_type(self.addon.name), self.version.version)

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

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_signing_error(self, sign_file_mock):
        sign_file_mock.side_effect = SigningError
        call_command('auto_approve')
        assert sign_file_mock.call_count == 1
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'error': 1, 'is_locked': 0,
                           'has_auto_approval_disabled': 0,
                           'is_recommendable': 0,
                           'should_be_delayed': 0})

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


class TestAutoApproveCommandTransactions(
        AutoApproveTestsMixin, TransactionTestCase):
    def setUp(self):
        user_factory(
            id=settings.TASK_USER_ID, username='taskuser',
            email='taskuser@mozilla.com')
        self.addons = [
            addon_factory(average_daily_users=666, users=[user_factory()]),
            addon_factory(average_daily_users=999, users=[user_factory()]),
        ]
        self.versions = [
            version_factory(
                addon=self.addons[0], file_kw={
                    'status': amo.STATUS_AWAITING_REVIEW,
                    'is_webextension': True}),
            version_factory(
                addon=self.addons[1], file_kw={
                    'status': amo.STATUS_AWAITING_REVIEW,
                    'is_webextension': True}),
        ]
        self.files = [
            self.versions[0].all_files[0],
            self.versions[1].all_files[0],
        ]
        self.versions[0].update(nomination=days_ago(1))
        FileValidation.objects.create(
            file=self.versions[0].all_files[0], validation=u'{}')
        FileValidation.objects.create(
            file=self.versions[1].all_files[0], validation=u'{}')
        super(TestAutoApproveCommandTransactions, self).setUp()

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_signing_error_roll_back(self, sign_file_mock):
        sign_file_mock.side_effect = [SigningError, None]
        call_command('auto_approve')
        # Make sure that the AutoApprovalSummary created for the first add-on
        # was rolled back because of the signing error, and that it didn't
        # affect the approval of the second one.
        assert sign_file_mock.call_count == 2

        for file_ in self.files:
            file_.reload()
        for addon in self.addons:
            addon.reload()

        assert not AutoApprovalSummary.objects.filter(
            version=self.versions[0]).exists()
        assert self.addons[0].status == amo.STATUS_APPROVED  # It already was.
        assert self.files[0].status == amo.STATUS_AWAITING_REVIEW
        assert not self.files[0].reviewed

        assert AutoApprovalSummary.objects.get(version=self.versions[1])
        assert self.addons[1].status == amo.STATUS_APPROVED
        assert self.files[1].status == amo.STATUS_APPROVED
        assert self.files[1].reviewed

        assert len(mail.outbox) == 1

        assert get_reviewing_cache(self.addons[0].pk) is None
        assert get_reviewing_cache(self.addons[1].pk) is None

        self._check_stats({'total': 2, 'error': 1, 'is_locked': 0,
                           'has_auto_approval_disabled': 0,
                           'auto_approved': 1, 'is_recommendable': 0,
                           'should_be_delayed': 0})


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
        author = user_factory(username=u'Authør')
        AddonUser.objects.create(addon=addon, user=author)
        # Add a pending info request expiring soon.
        flags = AddonReviewerFlags.objects.create(
            addon=addon,
            pending_info_request=datetime.now() + timedelta(hours=23),
            notified_about_expiring_info_request=False)
        # Create reviewer and staff users, and create the request for info
        # activity. Neither the reviewer nor the staff user should be cc'ed.
        reviewer = user_factory(username=u'Revièwer')
        self.grant_permission(reviewer, 'Addons:Review')
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, addon, addon.current_version,
            user=reviewer, details={'comments': u'Fly you fôöls!'})
        staff = user_factory(username=u'Staff Ûser')
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
