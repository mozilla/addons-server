# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from olympia.constants.scanners import DELAY_AUTO_APPROVAL, YARA
from django.core import mail
from django.core.management import call_command
from django.test.testcases import TransactionTestCase
from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, user_factory, version_factory)
from olympia.amo.utils import days_ago
from olympia.files.models import FileValidation
from olympia.files.utils import lock
from olympia.lib.crypto.signing import SigningError
from olympia.reviewers.management.commands import (
    auto_approve, auto_reject, notify_about_auto_approve_delay
)
from olympia.reviewers.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, get_reviewing_cache, set_reviewing_cache)
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.versions.models import Version, VersionReviewerFlags


class AutoApproveTestsMixin(object):
    def setUp(self):
        user_factory(
            id=settings.TASK_USER_ID, username='taskuser',
            email='taskuser@mozilla.com')

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

    def create_base_test_addon(self):
        self.addon = addon_factory(name='Basic Addøn', average_daily_users=666)
        self.version = version_factory(
            addon=self.addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        self.file = self.version.all_files[0]
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

    def create_candidates(self):
        # We already have an add-on with a version awaiting review that should
        # be considered. Make sure its nomination and creation date is in the
        # past to test ordering.
        self.version.update(
            created=self.days_ago(1), nomination=self.days_ago(1)
        )
        # Add a second file to self.version to test the distinct().
        file_factory(
            version=self.version, status=amo.STATUS_AWAITING_REVIEW,
            is_webextension=True)
        # Add reviewer flags disabling auto-approval for this add-on. It would
        # still be fetched as a candidate, just rejected later on when
        # calculating the verdict.
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled=True)

        # Add nominated add-on: it should be considered.
        new_addon = addon_factory(
            name='New Addon',
            status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        new_addon_version = new_addon.versions.all()[0]
        new_addon_version.update(
            created=self.days_ago(2), nomination=self.days_ago(2))
        # Even add an empty reviewer flags instance, that should not matter.
        AddonReviewerFlags.objects.create(addon=new_addon)

        # Add langpack: it should be considered.
        langpack = addon_factory(
            name='Langpack',
            type=amo.ADDON_LPAPP, status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        langpack_version = langpack.versions.all()[0]
        langpack_version.update(
            created=self.days_ago(3), nomination=self.days_ago(3))

        # Add a dictionary: it should also be considered.
        dictionary = addon_factory(
            name='Dictionary',
            type=amo.ADDON_DICT, status=amo.STATUS_NOMINATED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        dictionary_version = dictionary.versions.all()[0]
        dictionary_version.update(
            created=self.days_ago(4), nomination=self.days_ago(4))

        # search engine plugins are considered now
        search_addon = addon_factory(name='Search', type=amo.ADDON_SEARCH)
        search_addon_version = version_factory(
            addon=search_addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True},
            created=self.days_ago(5), nomination=self.days_ago(5))

        # Some recommended add-ons - one nominated and one update.
        # They should be considered by fetch_candidates(), so that they get a
        # weight assigned etc - they will not be auto-approved but that's
        # handled at a later stage, when calculating the verdict.
        recommendable_addon_nominated = addon_factory(
            name='Recommendable Addon',
            status=amo.STATUS_NOMINATED,
            recommended=True,
            version_kw={
                'nomination': self.days_ago(6),
                'created': self.days_ago(6),
            },
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True},
        )

        recommended_addon = addon_factory(
            name='Recommended Addon',
            recommended=True,
            version_kw={'recommendation_approved': False})
        recommended_addon_version = version_factory(
            addon=recommended_addon,
            recommendation_approved=True,
            nomination=self.days_ago(7),
            created=self.days_ago(7),
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True
            })

        # Add-on with 3 versions:
        # - one webext, listed, public.
        # - one non-listed webext version awaiting review.
        # - one listed non-webext awaiting review (should be ignored)
        complex_addon = addon_factory(
            name='Complex Addon', file_kw={'is_webextension': True})
        complex_addon_version = version_factory(
            nomination=self.days_ago(8),
            created=self.days_ago(8),
            addon=complex_addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'is_webextension': True,
                     'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            nomination=self.days_ago(9),
            created=self.days_ago(9),
            addon=complex_addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW}
        )

        # Add-on with an already public version and an unlisted webext
        # awaiting review.
        complex_addon_2 = addon_factory(
            name='Second Complex Addon', file_kw={'is_webextension': True})
        complex_addon_2_version = version_factory(
            addon=complex_addon_2, channel=amo.RELEASE_CHANNEL_UNLISTED,
            nomination=self.days_ago(10),
            created=self.days_ago(10),
            file_kw={'is_webextension': True,
                     'status': amo.STATUS_AWAITING_REVIEW}
        )

        # Disabled version with a webext waiting review (Still has to be
        # considered because unlisted doesn't care about disabled by user
        # state.
        user_disabled_addon = addon_factory(
            name='Disabled by user waiting review',
            disabled_by_user=True)
        user_disabled_addon_version = version_factory(
            nomination=self.days_ago(11),
            created=self.days_ago(11),
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            addon=user_disabled_addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True}
        )

        # Pure unlisted upload. Addon status is "incomplete" as a result, but
        # it should still be considered because unlisted versions don't care
        # about that.
        pure_unlisted = addon_factory(name='Pure unlisted', version_kw={
            'channel': amo.RELEASE_CHANNEL_UNLISTED,
            'nomination': self.days_ago(12),
            'created': self.days_ago(12)}, file_kw={
            'is_webextension': True, 'status': amo.STATUS_AWAITING_REVIEW
        }, status=amo.STATUS_NULL)
        pure_unlisted_version = pure_unlisted.versions.get()

        # Unlisted static theme.
        unlisted_theme = addon_factory(name='Unlisted theme', version_kw={
            'channel': amo.RELEASE_CHANNEL_UNLISTED,
            'nomination': self.days_ago(13),
            'created': self.days_ago(13)}, file_kw={
            'is_webextension': True, 'status': amo.STATUS_AWAITING_REVIEW
        }, status=amo.STATUS_NULL, type=amo.ADDON_STATICTHEME)
        unlisted_theme_version = unlisted_theme.versions.get()

        # ---------------------------------------------------------------------
        # Add a bunch of add-ons in various states that should not be returned.
        # Public add-on with no updates.
        addon_factory(name='Already Public', file_kw={'is_webextension': True})

        # Mozilla Disabled add-on with updates.
        disabled_addon = addon_factory(
            name='Mozilla Disabled', status=amo.STATUS_DISABLED,
        )
        version_factory(addon=disabled_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW,
            'is_webextension': True}
        )

        # Add-on with deleted version.
        addon_with_deleted_version = addon_factory(
            name='With deleted version awaiting review')
        deleted_version = version_factory(
            addon=addon_with_deleted_version, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True}
        )
        deleted_version.delete()

        # Add-on with a non-webextension update.
        non_webext_addon = addon_factory(name='Non Webext waiting review')
        version_factory(addon=non_webext_addon, file_kw={
            'status': amo.STATUS_AWAITING_REVIEW}
        )

        # Somehow deleted add-on with a file still waiting for review.
        deleted_addon = addon_factory(
            name='Deleted Awaiting Review Somehow', status=amo.STATUS_DELETED,
        )
        version_factory(
            addon=deleted_addon, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True}
        )

        # listed version belonging to an add-on disabled by user
        addon_factory(
            name='Listed Disabled by user',
            disabled_by_user=True,
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True
            }
        )

        # Incomplete listed addon
        addon_factory(
            name='Incomplete listed',
            status=amo.STATUS_NULL,
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True
            }
        )

        # Listed static theme
        addon_factory(name='Listed theme', file_kw={
            'is_webextension': True, 'status': amo.STATUS_AWAITING_REVIEW
        }, status=amo.STATUS_NOMINATED, type=amo.ADDON_STATICTHEME)

        return [(version.addon, version) for version in [
            unlisted_theme_version,
            pure_unlisted_version,
            user_disabled_addon_version,
            complex_addon_2_version,
            complex_addon_version,
            recommended_addon_version,
            recommendable_addon_nominated.current_version,
            search_addon_version,
            dictionary.current_version,
            langpack.current_version,
            new_addon.current_version,
            self.version,
        ]]


class TestAutoApproveCommand(AutoApproveTestsMixin, TestCase):
    def setUp(self):
        self.create_base_test_addon()
        super(TestAutoApproveCommand, self).setUp()

    def test_fetch_candidates(self):
        # Create the candidates and extra addons & versions that should not be
        # considered for auto-approval.
        expected = self.create_candidates()

        # Gather the candidates.
        command = auto_approve.Command()
        command.post_review = True
        qs = command.fetch_candidates()

        # Test that they are all present.
        assert [(version.addon, version) for version in qs] == expected

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
        assert (
            review_helper_mock().handler.approve_latest_version.call_count == 1
        )
        assert statsd_incr_mock.call_count == 1
        assert statsd_incr_mock.call_args == (
            ('reviewers.auto_approve.approve.success',), {}
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
            str(self.addon.name), self.version.version)

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
        self._check_stats({
            'total': 1,
            'error': 1,
            'has_auto_approval_disabled': 0,
            'is_locked': 0,
            'is_promoted_prereview': 0,
            'should_be_delayed': 0,
            'is_blocked': 0,
        })

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
        with lock(settings.TMP_PATH, auto_approve.LOCK_NAME):
            call_command('auto_approve')

        assert self.log_final_summary_mock.call_count == 0
        assert self.file.reload().status == amo.STATUS_AWAITING_REVIEW

    @mock.patch.object(ScannerResult, 'run_action')
    def test_does_not_execute_run_action_when_switch_is_inactive(
            self, run_action_mock):
        call_command('auto_approve')

        assert not run_action_mock.called

    @mock.patch.object(ScannerResult, 'run_action')
    def test_executes_run_action_when_switch_is_active(self, run_action_mock):
        self.create_switch('run-action-in-auto-approve', active=True)

        call_command('auto_approve')

        assert run_action_mock.called
        run_action_mock.assert_called_with(self.version)

    @mock.patch.object(ScannerResult, 'run_action')
    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_only_executes_run_action_once(self,
                                           sign_file_mock,
                                           run_action_mock):
        self.create_switch('run-action-in-auto-approve', active=True)
        call_command('auto_approve')

        assert run_action_mock.called
        run_action_mock.assert_called_with(self.version)

        run_action_mock.reset_mock()
        call_command('auto_approve')

        assert not run_action_mock.called

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_run_action_delay_approval(self, sign_file_mock):
        # Functional test making sure that the scanners _delay_auto_approval()
        # action properly delays auto-approval on the version it's applied to
        def check_assertions():
            aps = self.version.autoapprovalsummary
            assert aps.has_auto_approval_disabled

            flags = self.addon.reviewerflags
            assert flags.auto_approval_delayed_until

            assert not sign_file_mock.called

        self.create_switch('run-action-in-auto-approve', active=True)
        ScannerRule.objects.create(
            is_active=True, name='foo', action=DELAY_AUTO_APPROVAL,
            scanner=YARA)
        result = ScannerResult.objects.create(
            scanner=YARA, version=self.version,
            results=[{'rule': 'foo', 'tags': [], 'meta': {}}])
        assert result.has_matches

        call_command('auto_approve')
        check_assertions()

        call_command('auto_approve')  # Shouldn't matter if it's called twice.
        check_assertions()

    def test_run_action_delay_approval_unlisted(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.test_run_action_delay_approval()


class TestAutoApproveCommandTransactions(
        AutoApproveTestsMixin, TransactionTestCase):
    def setUp(self):
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

        self._check_stats({
            'total': 2,
            'error': 1,
            'auto_approved': 1,
            'has_auto_approval_disabled': 0,
            'is_locked': 0,
            'is_promoted_prereview': 0,
            'should_be_delayed': 0,
            'is_blocked': 0,
        })


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


class TestSendPendingRejectionLastWarningNotification(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory(pk=settings.TASK_USER_ID)

    def test_not_pending_rejection(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            # Add some activity logs, but no pending_rejection flag.
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_not_close_to_deadline(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(days=2))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_addon_already_not_public(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        # Disabled by user: we don't notify.
        addon.update(disabled_by_user=True)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

        # Disabled by mozilla: we don't notify.
        addon.update(disabled_by_user=False, status=amo.STATUS_DISABLED)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

        # Deleted: we don't notify.
        addon.update(status=amo.STATUS_DELETED)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_versions_already_disabled(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
            # Disable files: we should be left with no versions to notify the
            # developers about, since they have already been disabled.
            version.files.update(status=amo.STATUS_DISABLED)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_more_recent_version_unreviewed_not_pending_rejection(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon, file_kw={'status': amo.STATUS_DISABLED})
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        # Add another version not pending rejection but unreviewed: we should
        # not notify developers in that case.
        version_factory(
            addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_more_recent_version_public_not_pending_rejection(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon, file_kw={'status': amo.STATUS_DISABLED})
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        # Add another version public and not pending rejection: we should
        # not notify developers in that case.
        version_factory(addon=addon)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_notification_already_sent_for_this_addon(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        # Developers were already notified for this add-on, so we don't do it
        # again.
        AddonReviewerFlags.objects.create(
            addon=addon, notified_about_expiring_delayed_rejections=True)
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_pending_rejection_close_to_deadline(self):
        author = user_factory()
        addon = addon_factory(users=[author], version_kw={'version': '42.0'})
        version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version,
                details={'comments': 'Some cômments'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.subject == (
            'Mozilla Add-ons: %s will be disabled on addons.mozilla.org'
            % str(addon.name)
        )
        assert message.to == [author.email]
        assert 'Some cômments' in message.body
        for version in addon.versions.all():
            assert version.version in message.body

    def test_pending_rejection_one_version_already_disabled(self):
        author = user_factory()
        addon = addon_factory(users=[author], version_kw={'version': '42.0'})
        current_version = addon.current_version
        disabled_version = version_factory(
            addon=addon, version='42.1',
            file_kw={'status': amo.STATUS_DISABLED})
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.to == [author.email]
        assert 'fôo' in message.body
        assert current_version.version in message.body
        assert disabled_version.version not in message.body

    def test_more_recent_version_disabled(self):
        author = user_factory()
        addon = addon_factory(users=[author], version_kw={'version': '42.0'})
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        more_recent_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_DISABLED},
            version='42.2')
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.to == [author.email]
        assert 'fôo' in message.body
        assert version1.version in message.body
        assert version2.version in message.body
        assert more_recent_version.version not in message.body

    def test_more_recent_version_deleted(self):
        author = user_factory()
        addon = addon_factory(users=[author], version_kw={'version': '42.0'})
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        more_recent_version = version_factory(addon=addon, version='43.0')
        more_recent_version.delete()
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.to == [author.email]
        assert 'fôo' in message.body
        assert version1.version in message.body
        assert version2.version in message.body
        assert more_recent_version.version not in message.body

    def test_more_recent_version_pending_rejection_as_well(self):
        author = user_factory()
        addon = addon_factory(users=[author], version_kw={'version': '42.0'})
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        more_recent_version = version_factory(addon=addon)
        VersionReviewerFlags.objects.create(
            version=more_recent_version,
            pending_rejection=datetime.now() + timedelta(days=3))
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.to == [author.email]
        assert 'fôo' in message.body
        assert version1.version in message.body
        assert version2.version in message.body
        assert more_recent_version.version not in message.body

    def test_multiple_addons_pending_rejection_close_to_deadline(self):
        author1 = user_factory()
        addon1 = addon_factory(users=[author1], version_kw={'version': '42.0'})
        version11 = addon1.current_version
        version12 = version_factory(addon=addon1, version='42.1')
        author2 = user_factory()
        addon2 = addon_factory(users=[author2], version_kw={'version': '22.0'})
        version21 = addon2.current_version
        version22 = version_factory(addon=addon2, version='22.1')
        for version in Version.objects.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_CONTENT_DELAYED,
                version.addon, version,
                details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 2
        assert addon1.reviewerflags.notified_about_expiring_delayed_rejections
        assert addon2.reviewerflags.notified_about_expiring_delayed_rejections
        # Addons are processed in order of their pks.
        message = mail.outbox[0]
        assert message.to == [author1.email]
        assert str(addon1.name) in message.subject
        assert 'fôo' in message.body
        assert version11.version in message.body
        assert version12.version in message.body

        message = mail.outbox[1]
        assert message.to == [author2.email]
        assert str(addon2.name) in message.subject
        assert 'fôo' in message.body
        assert version21.version in message.body
        assert version22.version in message.body

    def test_somehow_no_activity_log_skip(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            # The ActivityLog doesn't match a pending rejection, so we should
            # not send the notification here.
            ActivityLog.create(
                amo.LOG.REJECT_VERSION,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_somehow_no_activity_log_details_skip(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            # The ActivityLog doesn't have details, so we should
            # not send the notification here.
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, user=self.user)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_somehow_no_activity_log_comments_skip(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            # The ActivityLog doesn't have comments, so we should
            # not send the notification here.
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, user=self.user, details={'foo': 'bar'})
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_multiple_developers_are_notified(self):
        author1 = user_factory()
        author2 = user_factory()
        addon = addon_factory(users=[author1, author2])
        version_factory(addon=addon)
        for version in addon.versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now() + timedelta(hours=23))
            ActivityLog.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon, version, details={'comments': 'fôo'}, user=self.user)
        more_recent_version = version_factory(addon=addon)
        VersionReviewerFlags.objects.create(
            version=more_recent_version,
            pending_rejection=datetime.now() + timedelta(days=3))
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 2
        message1 = mail.outbox[0]
        message2 = mail.outbox[1]
        assert message1.body == message2.body
        assert message1.subject == message2.subject
        assert message1.to != message2.to
        assert set(message1.to + message2.to) == {author1.email, author2.email}


class TestNotifyAboutAutoApproveDelay(AutoApproveTestsMixin, TestCase):
    def test_fetch_versions_waiting_for_approval_for_too_long(self):
        self.create_base_test_addon()
        expected = self.create_candidates()
        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()

        # Test that they are all present (all created date created by
        # create_candidates() are far enough in the past)
        assert [(version.addon, version) for version in qs] == expected

        # Reset created for a few selected add-ons to be more recent and
        # they should no longer be present (remove them from expected and
        # re-test)
        addon, version = expected.pop(0)
        version.update(created=datetime.now())
        addon, version = expected.pop(0)
        version.update(created=datetime.now() - timedelta(
            hours=command.WAITING_PERIOD_HOURS) + timedelta(seconds=30))
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert [(version.addon, version) for version in qs] == expected

        # Set notified_about_auto_approval_delay=True for an add-on and
        # it should no longer be present (remove it from expected and re-test)
        addon, version = expected.pop(0)
        AddonReviewerFlags.objects.create(
            addon=addon, notified_about_auto_approval_delay=True)
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert [(version.addon, version) for version in qs] == expected

    def test_fetch_versions_waiting_for_approval_for_too_long_reset(self):
        """Ensure we only consider the latest auto-approvable version for each
        add-on."""
        self.create_base_test_addon()
        old_version = self.version
        old_version.update(
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            created=self.days_ago(2), nomination=self.days_ago(2)
        )
        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert qs.count() == 1
        assert qs[0] == self.version

        # When we submit a new version, if it's waiting for approval as well,
        # it "resets" the waiting period.
        new_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED, file_kw={
                'status': amo.STATUS_AWAITING_REVIEW, 'is_webextension': True})

        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert qs.count() == 0

        # If the new version is old enough, then it's returned (and only this
        # version).
        new_version.update(created=self.days_ago(1))
        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert qs.count() == 1
        assert qs[0] == new_version

        # If the new version is approved but not the old one, then the old one
        # is returned, the new version no longer prevents the old one from
        # being considered.
        new_version.files.update(status=amo.STATUS_APPROVED)
        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert qs.count() == 1
        assert qs[0] == old_version

    def test_notify_nothing(self):
        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert not qs.exists()

        call_command('notify_about_auto_approve_delay')
        assert len(mail.outbox) == 0

    def test_notify_authors(self):
        # Not awaiting review.
        addon_factory(
            file_kw={'is_webextension': True},
            version_kw={'created': self.days_ago(1)}
        ).authors.add(user_factory())
        # Not awaiting review for long enough.
        addon_factory(
            file_kw={
                'is_webextension': True,
                'status': amo.STATUS_AWAITING_REVIEW,
            }
        ).authors.add(user_factory())
        # Valid.
        addon = addon_factory(
            file_kw={
                'is_webextension': True,
                'status': amo.STATUS_AWAITING_REVIEW
            },
            version_kw={'created': self.days_ago(1)})
        users = [user_factory(), user_factory()]
        [addon.authors.add(user) for user in users]

        command = notify_about_auto_approve_delay.Command()
        qs = command.fetch_versions_waiting_for_approval_for_too_long()
        assert qs.exists()

        assert not AddonReviewerFlags.objects.filter(addon=addon).exists()

        # Set up is done, let's call the command!
        call_command('notify_about_auto_approve_delay')

        addon.reload()

        assert len(mail.outbox) == 2
        assert mail.outbox[0].body == mail.outbox[1].body
        assert mail.outbox[0].subject == mail.outbox[1].subject
        subject = mail.outbox[0].subject
        assert subject == (
            'Mozilla Add-ons: %s %s is pending review' % (
                addon.name, addon.current_version.version
            )
        )
        body = mail.outbox[0].body
        assert 'Thank you for submitting your add-on' in body
        assert str(addon.name) in body
        assert str(addon.current_version.version) in body
        for message in mail.outbox:
            assert len(message.to) == 1
        assert (
            {message.to[0] for message in mail.outbox} ==
            {user.email for user in users}
        )

        assert addon.reviewerflags.notified_about_auto_approval_delay


class TestAutoReject(TestCase):
    def setUp(self):
        user_factory(
            id=settings.TASK_USER_ID, username='taskuser',
            email='taskuser@mozilla.com')
        self.addon = addon_factory(
            version_kw={'version': '1.0', 'created': self.days_ago(2)})
        self.version = self.addon.current_version
        self.file = self.version.all_files[0]
        self.yesterday = self.days_ago(1)
        VersionReviewerFlags.objects.create(
            version=self.version, pending_rejection=self.yesterday)

    def test_prevent_multiple_runs_in_parallel(self):
        # Create a lock manually, the command should exit immediately without
        # doing anything.
        with lock(settings.TMP_PATH, auto_reject.LOCK_NAME):
            call_command('auto_reject')

        self.addon.refresh_from_db()
        self.version.refresh_from_db()
        assert self.version.reviewerflags.pending_rejection
        assert self.version.is_public()
        assert self.addon.is_public()

    def test_fetch_addon_candidates_distinct(self):
        version = version_factory(
            addon=self.addon, version='0.9',
            created=self.days_ago(42))
        VersionReviewerFlags.objects.create(
            version=version, pending_rejection=self.yesterday)
        qs = auto_reject.Command().fetch_addon_candidates(now=datetime.now())
        assert list(qs) == [self.addon]

    def test_fetch_addon_candidates(self):
        pending_future_rejection = addon_factory()
        VersionReviewerFlags.objects.create(
            version=pending_future_rejection.current_version,
            pending_rejection=datetime.now() + timedelta(days=7))
        addon_factory()
        other_addon_with_pending_rejection = addon_factory(
            version_kw={'version': '10.0'})
        version_factory(
            addon=other_addon_with_pending_rejection, version='11.0')
        VersionReviewerFlags.objects.create(
            version=other_addon_with_pending_rejection.current_version,
            pending_rejection=self.yesterday)
        qs = auto_reject.Command().fetch_addon_candidates(now=datetime.now())
        assert list(qs) == [self.addon, other_addon_with_pending_rejection]

    def test_fetch_fetch_versions_candidates_for_addon(self):
        # self.version is already pending rejection, let's add more versions:
        # One that is also pending rejection.
        awaiting_review_pending_rejection = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.0')
        VersionReviewerFlags.objects.create(
            version=awaiting_review_pending_rejection,
            pending_rejection=self.yesterday)
        # One that is pending rejection in the future (it shouldn't be picked
        # up).
        future_pending_rejection = version_factory(
            addon=self.addon, version='3.0')
        VersionReviewerFlags.objects.create(
            version=future_pending_rejection,
            pending_rejection=datetime.now() + timedelta(days=7))
        # One that is just approved (it shouldn't be picked up).
        version_factory(addon=self.addon, version='4.0')

        qs = auto_reject.Command().fetch_version_candidates_for_addon(
            addon=self.addon, now=datetime.now())
        assert list(qs) == [
            self.version,
            awaiting_review_pending_rejection
        ]

    def test_deleted_addon(self):
        self.addon.delete()
        call_command('auto_reject')

        # Add-on stays deleted, version is rejected
        self.addon.refresh_from_db()
        self.file.refresh_from_db()
        assert self.addon.is_deleted
        assert self.file.status == amo.STATUS_DISABLED
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False).exists()

    def test_deleted_version(self):
        self.version.delete()
        call_command('auto_reject')

        # Version stays deleted & disabled
        self.addon.refresh_from_db()
        self.file.refresh_from_db()
        assert self.addon.status == amo.STATUS_NULL
        assert self.version.deleted
        assert self.file.status == amo.STATUS_DISABLED
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False).exists()

    def test_unlisted_version(self):
        self.make_addon_unlisted(self.addon)
        call_command('auto_reject')

        # Version stays unlisted, is disabled (even if that doesn't make much
        # sense to delay rejection of an unlisted version)
        self.addon.refresh_from_db()
        self.version.refresh_from_db()
        self.file.refresh_from_db()
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_DISABLED
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False).exists()

    def test_reject_versions(self):
        another_pending_rejection = version_factory(
            addon=self.addon, version='2.0')
        VersionReviewerFlags.objects.create(
            version=another_pending_rejection,
            pending_rejection=self.yesterday)

        command = auto_reject.Command()
        command.dry_run = False
        command.reject_versions(
            addon=self.addon,
            versions=[self.version, another_pending_rejection],
            latest_version=another_pending_rejection)

        # The versions should be rejected now.
        self.version.refresh_from_db()
        assert not self.version.is_public()
        another_pending_rejection.refresh_from_db()
        assert not self.version.is_public()

        # There should be an activity log for each version with the rejection.
        logs = ActivityLog.objects.for_addons(self.addon)
        assert len(logs) == 2
        assert logs[0].action == amo.LOG.REJECT_VERSION.id
        assert logs[0].arguments == [self.addon, self.version]
        assert logs[1].action == amo.LOG.REJECT_VERSION.id
        assert logs[1].arguments == [self.addon, another_pending_rejection]

        # All pending rejections flags in the past should have been dropped
        # when the rejection was applied (there are no other pending rejections
        # in this test).
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False).exists()

        # No mail should have gone out.
        assert len(mail.outbox) == 0

    def test_addon_locked(self):
        set_reviewing_cache(self.addon.pk, 42)
        call_command('auto_reject')

        self.addon.refresh_from_db()
        self.version.refresh_from_db()
        assert self.version.reviewerflags.pending_rejection
        assert self.version.is_public()
        assert self.addon.is_public()

    def test_addon_has_latest_version_unreviewed(self):
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.0')
        call_command('auto_reject')

        # Nothing should have been done: since there is a new version awaiting
        # review we consider the reviewer has fixed the issues from past
        # version(s) and are waiting on a reviewer decision before proceeding,
        # the old pending rejection is on hold.

        self.addon.refresh_from_db()
        self.version.refresh_from_db()
        assert self.version.reviewerflags.pending_rejection
        assert self.version.is_public()
        assert self.addon.is_public()

    def test_full_dry_run(self):
        call_command('auto_reject', '--dry-run')

        self.addon.refresh_from_db()
        self.version.refresh_from_db()
        assert self.version.reviewerflags.pending_rejection
        assert self.version.is_public()
        assert self.addon.is_public()

    def test_full_run(self):
        # Addon with a couple versions including its current_version pending
        # rejection, the add-on should be rejected with the versions
        all_pending_rejection = self.addon
        version = version_factory(
            addon=all_pending_rejection, version='0.9',
            created=self.days_ago(42))
        VersionReviewerFlags.objects.create(
            version=version, pending_rejection=self.yesterday)
        # Add-on with an old version pending rejection, but a newer one
        # approved: only the old one should be rejected.
        old_pending_rejection = addon_factory(
            version_kw={'version': '10.0', 'created': self.days_ago(2)})
        VersionReviewerFlags.objects.create(
            version=old_pending_rejection.current_version,
            pending_rejection=self.yesterday)
        new_version_old_pending_rejection = version_factory(
            addon=old_pending_rejection, version='11.0')
        # One with an old version approved, but a newer one pending
        # rejection: only the newer one should be rejected.
        new_pending_rejection = addon_factory(
            version_kw={'version': '20.0', 'created': self.days_ago(3)})
        new_pending_rejection_new_version = version_factory(
            addon=new_pending_rejection, version='21.0',
            created=self.days_ago(2))
        VersionReviewerFlags.objects.create(
            version=new_pending_rejection_new_version,
            pending_rejection=self.yesterday)
        # Add-on with a version pending rejection in the future, it shouldn't
        # be touched yet.
        future_pending_rejection = addon_factory()
        VersionReviewerFlags.objects.create(
            version=future_pending_rejection.current_version,
            pending_rejection=datetime.now() + timedelta(days=2))
        # Add-on not pending rejection, shouldn't be affected
        regular_addon = addon_factory()

        # Trigger the command!
        now = datetime.now()
        call_command('auto_reject')

        # First add-on and all its versions should have been rejected.
        all_pending_rejection.refresh_from_db()
        assert not all_pending_rejection.is_public()
        for version in all_pending_rejection.versions.all():
            assert not version.is_public()

        # Second one should still be public, only its old version rejected.
        old_pending_rejection.refresh_from_db()
        new_version_old_pending_rejection.refresh_from_db()
        assert old_pending_rejection.is_public()
        assert (
            old_pending_rejection.current_version ==
            new_version_old_pending_rejection)
        assert new_version_old_pending_rejection.is_public()
        assert not old_pending_rejection.versions.filter(
            version='10.0').get().is_public()

        # Third one should still be public, only its newer version rejected.
        new_pending_rejection.refresh_from_db()
        assert new_pending_rejection.is_public()
        assert (
            new_pending_rejection.current_version !=
            new_pending_rejection_new_version)
        assert not new_pending_rejection_new_version.is_public()
        assert new_pending_rejection.versions.filter(
            version='20.0').get().is_public()

        # Fourth one shouldn't have been touched because the pending rejection
        # for its version is in the future.
        future_pending_rejection.refresh_from_db()
        assert future_pending_rejection.is_public()
        assert future_pending_rejection.current_version
        assert future_pending_rejection.current_version.is_public()

        # Fifth one shouldn't have been touched.
        regular_addon.refresh_from_db()
        assert regular_addon.is_public()
        assert regular_addon.current_version
        assert regular_addon.current_version.is_public()

        # All pending rejections flags in the past should have been dropped
        # when the rejection was applied.
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__lt=now).exists()

        # No mail should have gone out.
        assert len(mail.outbox) == 0
