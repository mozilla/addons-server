import json
import uuid
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test.testcases import TransactionTestCase

import responses
from freezegun import freeze_time

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderJob, CinderPolicy, ContentDecision
from olympia.activity.models import ActivityLog, CinderPolicyLog, ReviewActionReasonLog
from olympia.addons.models import AddonApprovalsCounter, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.amo.utils import days_ago
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.scanners import DELAY_AUTO_APPROVAL, NARC, YARA
from olympia.files.models import FileManifest, FileValidation
from olympia.files.utils import lock
from olympia.lib.crypto.signing import SigningError
from olympia.ratings.models import Rating
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.versions.models import Version, VersionReviewerFlags

from ..management.commands import (
    auto_approve,
    auto_reject,
    backfill_reviewactionreasons_for_delayed_rejections,
)
from ..models import (
    AutoApprovalNoValidationResultError,
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewActionReason,
    get_reviewing_cache,
    set_reviewing_cache,
)


class AutoApproveTestsMixin:
    def setUp(self):
        user_factory(
            id=settings.TASK_USER_ID, username='taskuser', email='taskuser@mozilla.com'
        )

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
            addon=self.addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.file = self.version.file
        self.file_validation = FileValidation.objects.create(
            file=self.version.file, validation='{}'
        )
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

    def create_candidates(self):
        # We already have an add-on with a version awaiting review that should
        # be considered. Make sure its creation date is in the past to test ordering.
        self.version.update(created=self.days_ago(1), due_date=self.days_ago(-2))
        # Add reviewer flags disabling auto-approval for this add-on. It would
        # still be fetched as a candidate, just rejected later on when
        # calculating the verdict.
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)

        # Add nominated add-on: it should be considered.
        new_addon = addon_factory(
            name='New Addon',
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        new_addon_version = new_addon.versions.all()[0]
        new_addon_version.update(created=self.days_ago(2), due_date=self.days_ago(-1))
        # Even add an empty reviewer flags instance, that should not matter.
        AddonReviewerFlags.objects.create(addon=new_addon)

        # Add langpack with 2 listed versions awaiting review: both should be
        # considered.
        langpack = addon_factory(
            name='Langpack',
            type=amo.ADDON_LPAPP,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        langpack_version_one = langpack.versions.all()[0]
        langpack_version_one.update(created=self.days_ago(3), due_date=self.days_ago(0))
        langpack_version_two = version_factory(
            addon=langpack,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            created=self.days_ago(4),
            due_date=self.days_ago(0),
        )

        # Add a dictionary: it should also be considered.
        dictionary = addon_factory(
            name='Dictionary',
            type=amo.ADDON_DICT,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        dictionary_version = dictionary.versions.all()[0]
        dictionary_version.update(created=self.days_ago(5), due_date=self.days_ago(1))

        # Some recommended add-ons - one nominated and one update.
        # They should be considered by fetch_candidates(), so that they get a
        # weight assigned etc - they will not be auto-approved but that's
        # handled at a later stage, when calculating the verdict.
        recommendable_addon_nominated = addon_factory(
            name='Recommendable Addon',
            status=amo.STATUS_NOMINATED,
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            version_kw={
                'due_date': self.days_ago(3),
                'created': self.days_ago(6),
            },
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        recommended_addon = addon_factory(
            name='Recommended Addon',
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            version_kw={'promotion_approved': False},
        )
        recommended_addon_version = version_factory(
            addon=recommended_addon,
            promotion_approved=True,
            due_date=self.days_ago(4),
            created=self.days_ago(7),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Add-on with 2 versions:
        # - one listed, public.
        # - one non-listed version awaiting review.
        complex_addon = addon_factory(name='Complex Addon')
        complex_addon_version = version_factory(
            due_date=self.days_ago(5),
            created=self.days_ago(8),
            addon=complex_addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Disabled version with a file waiting review (Still has to be
        # considered because unlisted doesn't care about disabled by user
        # state.
        user_disabled_addon = addon_factory(
            name='Disabled by user waiting review', disabled_by_user=True
        )
        user_disabled_addon_version = version_factory(
            due_date=self.days_ago(8),
            created=self.days_ago(11),
            channel=amo.CHANNEL_UNLISTED,
            addon=user_disabled_addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Pure unlisted upload. Addon status is "incomplete" as a result, but
        # it should still be considered because unlisted versions don't care
        # about that.
        pure_unlisted = addon_factory(
            name='Pure unlisted',
            version_kw={
                'channel': amo.CHANNEL_UNLISTED,
                'due_date': self.days_ago(9),
                'created': self.days_ago(12),
            },
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NULL,
        )
        pure_unlisted_version = pure_unlisted.versions.get()

        # Unlisted static theme.
        unlisted_theme = addon_factory(
            name='Unlisted theme',
            version_kw={
                'channel': amo.CHANNEL_UNLISTED,
                'due_date': self.days_ago(10),
                'created': self.days_ago(13),
            },
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NULL,
            type=amo.ADDON_STATICTHEME,
        )
        unlisted_theme_version = unlisted_theme.versions.get()

        # ---------------------------------------------------------------------
        # Add a bunch of add-ons in various states that should not be returned.
        # Public add-on with no updates.
        addon_factory(name='Already Public')

        # Mozilla Disabled add-on with updates.
        disabled_addon = addon_factory(
            name='Mozilla Disabled',
            status=amo.STATUS_DISABLED,
        )
        version_factory(
            addon=disabled_addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Add-on with deleted version.
        addon_with_deleted_version = addon_factory(
            name='With deleted version awaiting review'
        )
        deleted_version = version_factory(
            addon=addon_with_deleted_version,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        deleted_version.delete()

        # Somehow deleted add-on with a file still waiting for review.
        deleted_addon = addon_factory(
            name='Deleted Awaiting Review Somehow',
            status=amo.STATUS_DELETED,
        )
        version_factory(
            addon=deleted_addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # listed version belonging to an add-on disabled by user
        addon_factory(
            name='Listed Disabled by user',
            disabled_by_user=True,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Incomplete listed addon
        addon_factory(
            name='Incomplete listed',
            status=amo.STATUS_NULL,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

        # Listed static theme
        addon_factory(
            name='Listed theme',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
        )

        return [
            (version.addon, version)
            for version in [
                unlisted_theme_version,
                pure_unlisted_version,
                user_disabled_addon_version,
                complex_addon_version,
                recommended_addon_version,
                recommendable_addon_nominated.current_version,
                dictionary.current_version,
                langpack_version_two,
                langpack_version_one,
                new_addon.current_version,
                self.version,
            ]
        ]


class TestAutoApproveCommand(AutoApproveTestsMixin, TestCase):
    def setUp(self):
        self.create_base_test_addon()
        super().setUp()

    def test_fetch_candidates(self):
        # Create the candidates and extra addons & versions that should not be
        # considered for auto-approval.
        candidates = self.create_candidates()
        expected = [version.id for addon, version in candidates]

        # Gather the candidates.
        command = auto_approve.Command()
        qs = command.fetch_candidates()

        # Test that they are all present.
        assert list(qs) == expected

    @mock.patch('olympia.reviewers.management.commands.auto_approve.statsd.incr')
    @mock.patch('olympia.reviewers.management.commands.auto_approve.ReviewHelper')
    def test_approve(self, review_helper_mock, statsd_incr_mock):
        review_helper_mock.return_value.actions = {'public': mock.MagicMock()}
        command = auto_approve.Command()
        command.approve(self.version)
        assert review_helper_mock.call_count == 1
        assert review_helper_mock.call_args == (
            (),
            {
                'addon': self.addon,
                'version': self.version,
                'human_review': False,
                'channel': self.version.channel,
            },
        )
        assert review_helper_mock().actions['public']['method'].call_count == 1
        assert statsd_incr_mock.call_count == 1
        assert statsd_incr_mock.call_args == (
            ('reviewers.auto_approve.approve.success',),
            {},
        )

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_full_run(self, sign_file_mock):
        # Simple integration test with as few mocks as possible.
        assert not AutoApprovalSummary.objects.exists()
        assert not self.file.approval_date
        self.author = user_factory()
        self.addon.addonuser_set.create(user=self.author)

        # Delete the add-on current version and approval info, leaving it
        # nominated. Set its creation date in the past and it should be
        # picked up and auto-approved.
        AddonApprovalsCounter.objects.filter(addon=self.addon).get().delete()
        self.addon.current_version.delete()
        self.version.update(created=self.days_ago(2))
        self.addon.update_status()

        ActivityLog.objects.all().delete()

        call_command('auto_approve', '--dry-run')

        assert ActivityLog.objects.count() == 0

        call_command('auto_approve')

        self.addon.reload()
        self.file.reload()
        assert AutoApprovalSummary.objects.count() == 1
        summary = AutoApprovalSummary.objects.get(version=self.version)
        assert summary
        assert get_reviewing_cache(self.addon.pk) is None
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.file.approval_date
        assert ActivityLog.objects.count()
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.APPROVE_VERSION.id
        assert sign_file_mock.call_count == 1
        assert sign_file_mock.call_args[0][0] == self.file
        # Can't test sending the mail here because TestCase doesn't handle
        # transactions so on_commit never fires. It's tested in
        # TestAutoApproveCommandTransactions below.
        return summary

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_multiple_langpacks_awaiting_review_are_both_approved(self, sign_file_mock):
        # Spot check langpack versions in particular, they both should be
        # approved.
        self.author = user_factory()
        self.addon.addonuser_set.create(user=self.author)
        self.addon.update(type=amo.ADDON_LPAPP)

        FileValidation.objects.create(
            file=version_factory(
                addon=self.addon,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ).file,
            validation='{}',
        )

        call_command('auto_approve')

        assert (
            self.addon.versions.filter(file__status=amo.STATUS_APPROVED).count()
            == self.addon.versions.count()
        )

    def test_full_with_weights(self):
        AbuseReport.objects.create(guid=self.addon.guid)
        Rating.objects.create(
            addon=self.addon, version=self.version, user=user_factory(), rating=2
        )
        self.file_validation.update(
            validation=json.dumps(
                {
                    'messages': [
                        {'id': ['DANGEROUS_EVAL']},
                    ]
                }
            )
        )
        summary = self.test_full_run()
        assert summary.weight == 65
        assert summary.metadata_weight == 15
        assert summary.code_weight == 50

    @mock.patch.object(auto_approve, 'set_reviewing_cache')
    @mock.patch.object(auto_approve, 'clear_reviewing_cache')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_locking(
        self,
        create_summary_for_version_mock,
        clear_reviewing_cache_mock,
        set_reviewing_cache_mock,
    ):
        create_summary_for_version_mock.return_value = (AutoApprovalSummary(), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert set_reviewing_cache_mock.call_count == 1
        assert set_reviewing_cache_mock.call_args == (
            (self.addon.pk, settings.TASK_USER_ID),
            {},
        )
        assert clear_reviewing_cache_mock.call_count == 1
        assert clear_reviewing_cache_mock.call_args == ((self.addon.pk,), {})

    @mock.patch.object(auto_approve, 'set_reviewing_cache')
    @mock.patch.object(auto_approve, 'clear_reviewing_cache')
    @mock.patch.object(AutoApprovalSummary, 'check_is_locked')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_no_locking_if_already_locked(
        self,
        create_summary_for_version_mock,
        check_is_locked_mock,
        clear_reviewing_cache_mock,
        set_reviewing_cache_mock,
    ):
        check_is_locked_mock.return_value = True
        create_summary_for_version_mock.return_value = (AutoApprovalSummary(), {})
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert set_reviewing_cache_mock.call_count == 0
        assert clear_reviewing_cache_mock.call_count == 0

    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_no_validation_result(self, create_summary_for_version_mock):
        create_summary_for_version_mock.side_effect = (
            AutoApprovalNoValidationResultError
        )
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
        self._check_stats(
            {
                'total': 1,
                'error': 1,
                'has_auto_approval_disabled': 0,
                'is_locked': 0,
                'is_promoted_prereview': 0,
                'should_be_delayed': 0,
                'is_blocked': 0,
                'is_pending_rejection': 0,
            }
        )

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict_dry_run(
        self, create_summary_for_version_mock, approve_mock
    ):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED),
            {},
        )
        call_command('auto_approve', '--dry-run')
        assert approve_mock.call_count == 0
        assert create_summary_for_version_mock.call_args == (
            (self.version,),
            {'dry_run': True},
        )
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_successful_verdict(self, create_summary_for_version_mock, approve_mock):
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.AUTO_APPROVED),
            {},
        )
        call_command('auto_approve')
        assert create_summary_for_version_mock.call_count == 1
        assert create_summary_for_version_mock.call_args == (
            (self.version,),
            {'dry_run': False},
        )
        assert get_reviewing_cache(self.addon.pk) is None
        assert approve_mock.call_count == 1
        assert approve_mock.call_args == ((self.version,), {})
        self._check_stats({'total': 1, 'auto_approved': 1})

    @mock.patch.object(auto_approve.Command, 'approve')
    @mock.patch.object(auto_approve.Command, 'disapprove')
    @mock.patch.object(AutoApprovalSummary, 'create_summary_for_version')
    def test_failed_verdict(
        self, create_summary_for_version_mock, disapprove_mock, approve_mock
    ):
        fake_verdict_info = {'is_locked': True}
        create_summary_for_version_mock.return_value = (
            AutoApprovalSummary(verdict=amo.NOT_AUTO_APPROVED),
            fake_verdict_info,
        )
        call_command('auto_approve')
        assert approve_mock.call_count == 0
        assert disapprove_mock.call_count == 1
        assert create_summary_for_version_mock.call_args == (
            (self.version,),
            {'dry_run': False},
        )
        assert get_reviewing_cache(self.addon.pk) is None
        self._check_stats(
            {
                'total': 1,
                'is_locked': 1,
            }
        )

    def test_disapprove_is_promoted_prereview(self):
        self.version.autoapprovalsummary = AutoApprovalSummary(
            is_promoted_prereview=True
        )
        command = auto_approve.Command()
        command.disapprove(self.version)
        nhr = self.version.needshumanreview_set.get()
        assert nhr.reason == NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
        assert nhr.is_active

    def test_disapproves_has_auto_approval_disabled(self):
        self.version.autoapprovalsummary = AutoApprovalSummary(
            has_auto_approval_disabled=True
        )
        command = auto_approve.Command()
        command.disapprove(self.version)
        nhr = self.version.needshumanreview_set.get()
        assert nhr.reason == NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        assert nhr.is_active

    def test_disapproves_is_promoted_but_decision_waiting_for_2nd_level_exists(self):
        self.version.autoapprovalsummary = AutoApprovalSummary(
            is_promoted_prereview=True
        )
        decision = ContentDecision.objects.create(
            addon=self.addon, action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON
        )
        decision.target_versions.add(self.version)
        command = auto_approve.Command()
        command.disapprove(self.version)
        assert not self.version.needshumanreview_set.filter(is_active=True).exists()

        # Once the decision gets approved at the 2nd level, if the version is
        # still awaiting review, we flag it as normal.
        decision.update(action_date=datetime.now())
        command = auto_approve.Command()
        command.disapprove(self.version)
        assert self.version.needshumanreview_set.filter(is_active=True).exists()

    def test_prevent_multiple_runs_in_parallel(self):
        # Create a lock manually, the command should exit immediately without
        # doing anything.
        with lock(settings.TMP_PATH, auto_approve.LOCK_NAME):
            call_command('auto_approve')

        assert self.log_final_summary_mock.call_count == 0
        assert self.file.reload().status == amo.STATUS_AWAITING_REVIEW

    @mock.patch(
        'olympia.reviewers.management.commands.auto_approve.run_narc_on_version'
    )
    def test_does_not_execute_run_narc_on_version_when_switch_is_inactive(
        self, run_narc_mock
    ):
        call_command('auto_approve')

        assert run_narc_mock.call_count == 0

    @mock.patch(
        'olympia.reviewers.management.commands.auto_approve.run_narc_on_version'
    )
    def test_executes_run_narc_on_version_when_switch_is_active(self, run_narc_mock):
        self.create_switch('enable-narc', active=True)

        call_command('auto_approve')

        assert run_narc_mock.call_count == 1
        assert run_narc_mock.call_args[0] == (self.version.pk,)
        assert run_narc_mock.call_args[1] == {'run_action_on_match': False}

    @mock.patch(
        'olympia.reviewers.management.commands.auto_approve.run_narc_on_version'
    )
    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_only_executes_run_narc_on_version_once(
        self, sign_file_mock, run_narc_mock
    ):
        self.create_switch('enable-narc', active=True)
        call_command('auto_approve')

        assert run_narc_mock.call_count == 1
        assert run_narc_mock.call_args[0] == (self.version.pk,)
        assert run_narc_mock.call_args[1] == {'run_action_on_match': False}

        run_narc_mock.reset_mock()
        call_command('auto_approve')

        assert run_narc_mock.call_count == 0

    @mock.patch.object(ScannerResult, 'run_action')
    def test_does_not_execute_run_action_when_switch_is_inactive(self, run_action_mock):
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
    def test_only_executes_run_action_once(self, sign_file_mock, run_action_mock):
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

            self.addon.refresh_from_db()
            flags = self.addon.reviewerflags
            assert flags.auto_approval_delayed_until

            assert not sign_file_mock.called

        self.create_switch('run-action-in-auto-approve', active=True)
        ScannerRule.objects.create(
            is_active=True, name='foo', action=DELAY_AUTO_APPROVAL, scanner=YARA
        )
        result = ScannerResult.objects.create(
            scanner=YARA,
            version=self.version,
            results=[{'rule': 'foo', 'tags': [], 'meta': {}}],
        )
        assert result.has_matches

        call_command('auto_approve')
        check_assertions()

        call_command('auto_approve')  # Shouldn't matter if it's called twice.
        check_assertions()

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_run_action_delay_approval_with_run_narc(self, sign_file_mock):
        # Functional test making sure that the scanners _delay_auto_approval()
        # action properly delays auto-approval on the version it's applied to,
        # including when the scanner is narc (which is run in auto-approve).
        def check_assertions():
            assert self.version.scannerresults.count() == 1
            result = self.version.scannerresults.get()
            assert result.scanner == NARC
            assert result.has_matches
            assert result.results
            assert list(result.matched_rules.all()) == [rule]

            aps = self.version.autoapprovalsummary
            assert aps.has_auto_approval_disabled

            self.addon.refresh_from_db()
            flags = self.addon.reviewerflags
            assert flags.auto_approval_delayed_until

            assert not sign_file_mock.called

        self.create_switch('run-action-in-auto-approve', active=True)
        self.create_switch('enable-narc', active=True)
        rule = ScannerRule.objects.create(
            is_active=True,
            name='foo',
            action=DELAY_AUTO_APPROVAL,
            scanner=NARC,
            definition='.*',  # Would match anything.
        )
        # Fake file manifest data to avoid dealing with a real file. We want to
        # avoid resolve_webext_translations() which wants a real file...
        FileManifest.objects.create(
            file=self.version.file,
            manifest_data={
                'name': 'Foo',
            },
        )

        call_command('auto_approve')
        check_assertions()

        call_command('auto_approve')  # Shouldn't matter if it's called twice.
        check_assertions()

    def test_run_action_delay_approval_unlisted(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self.test_run_action_delay_approval()

    def test_run_disapprove(self):
        def check_assertions():
            # Hasn't been approved, a NHR was created.
            assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
            assert self.version.needshumanreview_set.count() == 1
            nhr = self.version.needshumanreview_set.get()
            assert nhr.reason == NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            assert nhr.is_active

        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        call_command('auto_approve')
        check_assertions()

        # Calling it again would not add more NHR instances.
        call_command('auto_approve')
        check_assertions()

    def test_run_disapprove_promoted(self):
        def check_assertions():
            # Hasn't been approved, a NHR was created.
            assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
            assert self.version.needshumanreview_set.count() == 1
            nhr = self.version.needshumanreview_set.get()
            assert nhr.reason == NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
            assert nhr.is_active

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.NOTABLE)
        call_command('auto_approve')
        check_assertions()

        # Calling it again would not add more NHR instances.
        call_command('auto_approve')
        check_assertions()

    def test_run_disapprove_pending_rejection(self):
        def check_assertions():
            # Hasn't been approved, but no NHR were created since it's pending
            # rejection already.
            assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
            assert not self.version.needshumanreview_set.exists()

        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        version_review_flags_factory(
            version=self.version, pending_rejection=datetime.now() + timedelta(hours=23)
        )
        call_command('auto_approve')
        check_assertions()

        # Calling it again would not add more NHR instances.
        call_command('auto_approve')
        check_assertions()


class TestAutoApproveCommandTransactions(AutoApproveTestsMixin, TransactionTestCase):
    def setUp(self):
        self.addons = [
            addon_factory(average_daily_users=666, users=[user_factory()]),
            addon_factory(average_daily_users=999, users=[user_factory()]),
        ]
        self.versions = [
            version_factory(
                addon=self.addons[0],
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ),
            version_factory(
                addon=self.addons[1],
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ),
        ]
        self.files = [
            self.versions[0].file,
            self.versions[1].file,
        ]
        self.versions[0].update(created=days_ago(1))
        FileValidation.objects.create(file=self.versions[0].file, validation='{}')
        FileValidation.objects.create(file=self.versions[1].file, validation='{}')
        super().setUp()

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

        assert not AutoApprovalSummary.objects.filter(version=self.versions[0]).exists()
        assert self.addons[0].status == amo.STATUS_APPROVED  # It already was.
        assert self.files[0].status == amo.STATUS_AWAITING_REVIEW
        assert not self.files[0].approval_date

        assert AutoApprovalSummary.objects.get(version=self.versions[1])
        assert self.addons[1].status == amo.STATUS_APPROVED
        assert self.files[1].status == amo.STATUS_APPROVED
        assert self.files[1].approval_date

        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == [self.addons[1].authors.all()[0].email]
        assert msg.from_email == settings.DEFAULT_FROM_EMAIL
        assert self.versions[1].version in msg.body

        assert get_reviewing_cache(self.addons[0].pk) is None
        assert get_reviewing_cache(self.addons[1].pk) is None

        self._check_stats(
            {
                'total': 2,
                'error': 1,
                'auto_approved': 1,
                'has_auto_approval_disabled': 0,
                'is_locked': 0,
                'is_promoted_prereview': 0,
                'should_be_delayed': 0,
                'is_blocked': 0,
                'is_pending_rejection': 0,
            }
        )


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
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_not_close_to_deadline(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(days=2)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_addon_already_not_public(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
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
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
            # Disable file: we should be left with no versions to notify the
            # developers about, since they have already been disabled.
            version.file.update(status=amo.STATUS_DISABLED)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_more_recent_version_unreviewed_not_pending_rejection(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon, file_kw={'status': amo.STATUS_DISABLED})
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        # Add another version not pending rejection but unreviewed: we should
        # not notify developers in that case.
        version_factory(addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_more_recent_version_public_not_pending_rejection(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon, file_kw={'status': amo.STATUS_DISABLED})
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
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
            addon=addon, notified_about_expiring_delayed_rejections=True
        )
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_pending_rejection_close_to_deadline_no_cinder_job(self):
        author = user_factory()
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'Some cômments'},
                user=self.user,
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert (
            message.subject == f'Mozilla Add-ons: {addon.name} [ref:Addon#{addon.id}]'
        )
        assert message.to == [author.email]
        assert 'Some cômments' in message.body
        for version in addon.versions.all():
            assert version.version in message.body
        assert 'right to appeal' not in message.body
        assert 'assessment performed on our own initiative' in message.body
        assert 'received from a third party' not in message.body

    def test_pending_rejection_close_to_deadline_with_cinder_job(self):
        author = user_factory()
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version = addon.current_version
        version_factory(addon=addon, version='42.1')
        cinder_job = CinderJob.objects.create(
            job_id='1',
            decision=ContentDecision.objects.create(
                cinder_id='13579',
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
                addon=addon,
            ),
        )
        AbuseReport.objects.create(guid=addon.guid, cinder_job=cinder_job)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'Some cômments'},
                user=self.user,
            )
        # The job was resolved with the first rejection, but will still be picked up.
        cinder_job.pending_rejections.add(version.reviewerflags)
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 1
        assert addon.reviewerflags.notified_about_expiring_delayed_rejections
        message = mail.outbox[0]
        assert message.subject == f'Mozilla Add-ons: {addon.name} [ref:13579]'
        assert message.to == [author.email]
        assert 'Some cômments' in message.body
        for version in addon.versions.all():
            assert version.version in message.body
        assert 'right to appeal' not in message.body
        assert 'assessment performed on our own initiative' not in message.body
        assert 'received from a third party' in message.body

    def test_pending_rejection_one_version_already_disabled(self):
        author = user_factory()
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        current_version = addon.current_version
        disabled_version = version_factory(
            addon=addon, version='42.1', file_kw={'status': amo.STATUS_DISABLED}
        )
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
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
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        more_recent_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_DISABLED}, version='42.2'
        )
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
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
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
        addon = addon_factory(
            users=[author], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version1 = addon.current_version
        version2 = version_factory(addon=addon, version='42.1')
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        more_recent_version = version_factory(addon=addon, version='43.0')
        version_review_flags_factory(
            version=more_recent_version,
            pending_rejection=datetime.now() + timedelta(days=3),
        )
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
        addon1 = addon_factory(
            users=[author1], version_kw={'version': amo.DEFAULT_WEBEXT_MIN_VERSION}
        )
        version11 = addon1.current_version
        version12 = version_factory(addon=addon1, version='42.1')
        author2 = user_factory()
        addon2 = addon_factory(users=[author2], version_kw={'version': '22.0'})
        version21 = addon2.current_version
        version22 = version_factory(addon=addon2, version='22.1')
        for version in Version.objects.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_CONTENT_DELAYED,
                version.addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
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
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            # The ActivityLog doesn't match a pending rejection, so we should
            # not send the notification here.
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_somehow_no_activity_log_details_skip(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            # The ActivityLog doesn't have details, so we should
            # not send the notification here.
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED, addon, version, user=self.user
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_somehow_no_activity_log_comments_skip(self):
        author = user_factory()
        addon = addon_factory(users=[author])
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            # The ActivityLog doesn't have comments, so we should
            # not send the notification here.
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                user=self.user,
                details={'foo': 'bar'},
            )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 0

    def test_multiple_developers_are_notified(self):
        author1 = user_factory()
        author2 = user_factory()
        addon = addon_factory(users=[author1, author2])
        version_factory(addon=addon)
        for version in addon.versions.all():
            version_review_flags_factory(
                version=version, pending_rejection=datetime.now() + timedelta(hours=23)
            )
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                details={'comments': 'fôo'},
                user=self.user,
            )
        more_recent_version = version_factory(addon=addon)
        version_review_flags_factory(
            version=more_recent_version,
            pending_rejection=datetime.now() + timedelta(days=3),
        )
        call_command('send_pending_rejection_last_warning_notifications')
        assert len(mail.outbox) == 2
        message1 = mail.outbox[0]
        message2 = mail.outbox[1]
        assert message1.body == message2.body
        assert message1.subject == message2.subject
        assert message1.to != message2.to
        assert set(message1.to + message2.to) == {author1.email, author2.email}


class AutoRejectTestsMixin:
    def setUp(self):
        self.task_user = user_factory(
            id=settings.TASK_USER_ID, username='taskuser', email='taskuser@mozilla.com'
        )
        self.author = user_factory()
        self.addon = addon_factory(
            version_kw={'version': '1.0', 'created': self.days_ago(2)},
            users=[self.author],
        )
        self.version = self.addon.current_version
        self.file = self.version.file
        self.yesterday = self.days_ago(1)
        self.user = user_factory()
        version_review_flags_factory(
            version=self.version,
            pending_rejection=self.yesterday,
            pending_rejection_by=self.user,
            pending_content_rejection=True,
        )

        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

    def days_ago(self, days):
        return days_ago(days)

    def _ensure_auto_approval_until_next_approval_is_not_set(self):
        # We shouldn't have disabled auto-approval until next approval when
        # performing automatic rejections.
        try:
            self.addon.reviewerflags.reload()
        except AddonReviewerFlags.DoesNotExist:
            pass
        assert not self.addon.auto_approval_disabled_until_next_approval
        assert not self.addon.auto_approval_disabled_until_next_approval_unlisted


class TestAutoReject(AutoRejectTestsMixin, TestCase):
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
            addon=self.addon, version='0.9', created=self.days_ago(42)
        )
        version_review_flags_factory(version=version, pending_rejection=self.yesterday)
        qs = auto_reject.Command().fetch_addon_candidates(now=datetime.now())
        assert list(qs) == [self.addon]

    def test_fetch_addon_candidates(self):
        pending_future_rejection = addon_factory()
        version_review_flags_factory(
            version=pending_future_rejection.current_version,
            pending_rejection=datetime.now() + timedelta(days=7),
        )
        addon_factory()
        other_addon_with_pending_rejection = addon_factory(
            version_kw={'version': '10.0'}
        )
        version_factory(addon=other_addon_with_pending_rejection, version='11.0')
        version_review_flags_factory(
            version=other_addon_with_pending_rejection.current_version,
            pending_rejection=self.yesterday,
        )
        qs = auto_reject.Command().fetch_addon_candidates(now=datetime.now())
        assert list(qs) == [self.addon, other_addon_with_pending_rejection]

    def test_fetch_fetch_versions_candidates_for_addon(self):
        # self.version is already pending rejection, let's add more versions:
        # One that is also pending rejection.
        awaiting_review_pending_rejection = version_factory(
            addon=self.addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.0',
        )
        version_review_flags_factory(
            version=awaiting_review_pending_rejection, pending_rejection=self.yesterday
        )
        # One that is pending rejection in the future (it shouldn't be picked
        # up).
        future_pending_rejection = version_factory(addon=self.addon, version='3.0')
        version_review_flags_factory(
            version=future_pending_rejection,
            pending_rejection=datetime.now() + timedelta(days=7),
        )
        # One that is just approved (it shouldn't be picked up).
        version_factory(addon=self.addon, version='4.0')

        qs = auto_reject.Command().fetch_version_candidates_for_addon(
            addon=self.addon, now=datetime.now()
        )
        assert list(qs) == [self.version, awaiting_review_pending_rejection]

    def test_deleted_addon(self):
        self.addon.delete()
        call_command('auto_reject')

        # Add-on stays deleted, version is rejected
        self.addon.refresh_from_db()
        self.file.refresh_from_db()
        assert self.addon.is_deleted
        assert self.file.status == amo.STATUS_DISABLED
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False
        ).exists()

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
            pending_rejection__isnull=False
        ).exists()

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
            pending_rejection__isnull=False
        ).exists()
        self._ensure_auto_approval_until_next_approval_is_not_set()

    def _test_reject_versions(self, *, activity_logs_to_keep=None, reasons=None):
        if activity_logs_to_keep is None:
            activity_logs_to_keep = []
        if reasons is None:
            reasons = []
        policies = [reason.cinder_policy for reason in reasons]
        another_pending_rejection = version_factory(addon=self.addon, version='2.0')
        version_review_flags_factory(
            version=another_pending_rejection,
            pending_rejection=self.yesterday,
            pending_rejection_by=self.user,
            pending_content_rejection=True,
        )
        ActivityLog.objects.for_addons(self.addon).exclude(
            id__in=[a.pk for a in activity_logs_to_keep]
        ).delete()

        command = auto_reject.Command()
        command.dry_run = False
        command.reject_versions(
            addon=self.addon,
            versions=[self.version, another_pending_rejection],
            latest_version=another_pending_rejection,
        )

        # The versions should be rejected now.
        self.version.refresh_from_db()
        assert not self.version.is_public()
        another_pending_rejection.refresh_from_db()
        assert not self.version.is_public()

        # There should be a single new activity log for the rejection
        # and one because the add-on is changing status as a result.
        logs = ActivityLog.objects.for_addons(self.addon).exclude(
            id__in=[a.pk for a in activity_logs_to_keep]
        )
        decision = ContentDecision.objects.filter(action_date__isnull=False).get()
        assert len(logs) == 2
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[0].arguments == [self.addon, amo.STATUS_NULL]
        assert logs[0].user == self.task_user
        assert logs[1].action == amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED.id
        expected_arguments = [
            self.addon,
            self.version,
            another_pending_rejection,
            *reasons,
            *policies,
            decision,
        ]
        assert logs[1].arguments == expected_arguments
        assert logs[1].user == self.user
        # All pending rejections flags in the past should have been dropped
        # when the rejection was applied (there are no other pending rejections
        # in this test).
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False
        ).exists()
        # The pending_rejection_by should also have been cleared.
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection_by__isnull=False
        ).exists()
        # And pending_content_rejection too
        assert not VersionReviewerFlags.objects.filter(
            pending_content_rejection__isnull=False
        ).exists()

    def test_reject_versions(self):
        self._test_reject_versions()
        self._ensure_auto_approval_until_next_approval_is_not_set()
        assert len(mail.outbox) == 1
        assert 'right to appeal' in mail.outbox[0].body

    def test_reject_versions_with_resolved_cinder_job(self):
        cinder_job = CinderJob.objects.create(
            job_id='1',
            decision=ContentDecision.objects.create(
                cinder_id='13579',
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
                addon=self.addon,
            ),
        )
        AbuseReport.objects.create(guid=self.addon.guid, cinder_job=cinder_job)
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}decisions/13579/override/',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        review_action_reason = ReviewActionReason.objects.create(
            cinder_policy=policies[0], canned_response='.'
        )
        cinder_job.pending_rejections.add(self.version.reviewerflags)
        log = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            self.addon,
            self.version,
            review_action_reason,
            details={'comments': 'Some cômments'},
            user=self.user,
        )

        self._test_reject_versions(
            activity_logs_to_keep=[log], reasons=[review_action_reason]
        )
        # We notify the addon developer (only) while resolving abuse reports
        assert len(mail.outbox) == 1
        assert 'Some cômments' in mail.outbox[0].body
        assert 'your Extension have been disabled'
        assert 'right to appeal' in mail.outbox[0].body

    def test_reject_versions_with_resolved_cinder_job_no_third_party(self):
        cinder_job = CinderJob.objects.create(
            job_id='2',
            decision=ContentDecision.objects.create(
                cinder_id='13579',
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
                addon=self.addon,
            ),
        )
        CinderJob.objects.create(
            job_id='1',
            decision=ContentDecision.objects.create(
                cinder_id='13578',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
                appeal_job=cinder_job,
            ),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}decisions/13579/override/',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policies = [CinderPolicy.objects.create(name='policy', uuid='12345678')]
        review_action_reason = ReviewActionReason.objects.create(
            cinder_policy=policies[0], canned_response='.'
        )
        cinder_job.pending_rejections.add(self.version.reviewerflags)
        log = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            self.addon,
            self.version,
            review_action_reason,
            details={'comments': 'Some cômments'},
            user=self.user,
        )

        self._test_reject_versions(
            activity_logs_to_keep=[log], reasons=[review_action_reason]
        )
        # We notify the addon developer while resolving cinder jobs
        assert len(mail.outbox) == 1
        assert 'Some cômments' in mail.outbox[0].body
        assert 'your Extension have been disabled' in mail.outbox[0].body
        assert 'in an assessment performed on our own initiative' in mail.outbox[0].body

    def test_reject_versions_with_multiple_delayed_rejections(self):
        cinder_job = CinderJob.objects.create(
            job_id='2',
            decision=ContentDecision.objects.create(
                cinder_id='13579',
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
                addon=self.addon,
            ),
        )
        CinderJob.objects.create(
            job_id='1',
            decision=ContentDecision.objects.create(
                cinder_id='13578',
                action=DECISION_ACTIONS.AMO_APPROVE,
                addon=self.addon,
                appeal_job=cinder_job,
            ),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}decisions/13579/override/',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policies = [
            CinderPolicy.objects.create(name='policy', uuid='12345678'),
            CinderPolicy.objects.create(name='policy 2', uuid='abcdef'),
        ]
        review_action_reason = ReviewActionReason.objects.create(
            name='A reason', cinder_policy=policies[0], canned_response='A'
        )
        review_action_reason2 = ReviewActionReason.objects.create(
            name='Another reason', cinder_policy=policies[1], canned_response='B'
        )
        cinder_job.pending_rejections.add(self.version.reviewerflags)
        # Create 2 ActivityLogs on different dates delay-rejecting that add-on,
        # with different comments.
        old_log = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            self.addon,
            self.version,
            review_action_reason,
            details={'comments': 'Some old cômments'},
            user=self.user,
            created=self.days_ago(1),
        )
        log = ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            self.addon,
            self.version,
            review_action_reason,
            review_action_reason2,
            details={'comments': 'Some cômments'},
            user=self.user,
        )
        # Make sure to keep both logs when calling test_reject_versions
        self._test_reject_versions(
            activity_logs_to_keep=[old_log, log],
            reasons=[review_action_reason, review_action_reason2],
        )
        # We notify the addon developer while resolving cinder jobs
        assert len(mail.outbox) == 1
        # Only the latest comment should be used.
        assert 'Some cômments' in mail.outbox[0].body
        assert 'Some old cômments' not in mail.outbox[0].body
        assert 'your Extension have been disabled' in mail.outbox[0].body
        assert 'in an assessment performed on our own initiative' in mail.outbox[0].body

    def test_reject_versions_different_user(self):
        # Add another version pending rejection, but this one was rejected by
        # another reviewer, so it should be processed separately, resulting in
        # 2 rejections.
        another_pending_rejection = version_factory(addon=self.addon, version='2.0')
        other_reviewer = user_factory()
        version_review_flags_factory(
            version=another_pending_rejection,
            pending_rejection=self.yesterday,
            pending_rejection_by=other_reviewer,
            pending_content_rejection=True,
        )
        ActivityLog.objects.for_addons(self.addon).delete()

        command = auto_reject.Command()
        command.dry_run = False
        command.reject_versions(
            addon=self.addon,
            versions=[self.version, another_pending_rejection],
            latest_version=another_pending_rejection,
        )

        # The versions should be rejected now.
        self.version.refresh_from_db()
        assert not self.version.is_public()
        another_pending_rejection.refresh_from_db()
        assert not self.version.is_public()

        # There should be a single activity log for the rejection
        # and one because the add-on is changing status as a result.
        logs = ActivityLog.objects.for_addons(self.addon)
        decision1, decision2 = list(ContentDecision.objects.all())
        assert len(logs) == 3
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[0].arguments == [self.addon, amo.STATUS_NULL]
        assert logs[0].user == self.task_user
        assert logs[1].action == amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED.id
        assert logs[1].arguments == [
            self.addon,
            self.version,
            decision1,
        ]
        assert logs[1].user == self.user
        assert logs[2].action == amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED.id
        assert logs[2].arguments == [
            self.addon,
            another_pending_rejection,
            decision2,
        ]
        assert logs[2].user == other_reviewer

        # All pending rejections flags in the past should have been dropped
        # when the rejection was applied (there are no other pending rejections
        # in this test).
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False
        ).exists()
        # The pending_rejection_by should also have been cleared.
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection_by__isnull=False
        ).exists()
        # And pending_content_rejection too
        assert not VersionReviewerFlags.objects.filter(
            pending_content_rejection__isnull=False
        ).exists()

        assert len(mail.outbox) == 2
        assert 'right to appeal' in mail.outbox[0].body
        assert 'right to appeal' in mail.outbox[1].body

    def test_reject_versions_different_action(self):
        # Add another version pending rejection, but for this one it's not a
        # content rejection, so it should be processed separately, resulting in
        # 2 rejections.
        another_pending_rejection = version_factory(addon=self.addon, version='2.0')
        version_review_flags_factory(
            version=another_pending_rejection,
            pending_rejection=self.yesterday,
            pending_rejection_by=self.user,
            pending_content_rejection=False,
        )
        ActivityLog.objects.for_addons(self.addon).delete()

        command = auto_reject.Command()
        command.dry_run = False
        command.reject_versions(
            addon=self.addon,
            versions=[self.version, another_pending_rejection],
            latest_version=another_pending_rejection,
        )

        # The versions should be rejected now.
        self.version.refresh_from_db()
        assert not self.version.is_public()
        another_pending_rejection.refresh_from_db()
        assert not self.version.is_public()

        # There should be a single activity log for the rejection
        # and one because the add-on is changing status as a result.
        logs = ActivityLog.objects.for_addons(self.addon)
        decision1, decision2 = list(ContentDecision.objects.all())
        assert len(logs) == 3
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[0].arguments == [self.addon, amo.STATUS_NULL]
        assert logs[0].user == self.task_user
        assert logs[1].action == amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED.id
        assert logs[1].arguments == [
            self.addon,
            self.version,
            decision1,
        ]
        assert logs[1].user == self.user
        assert logs[2].action == amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED.id
        assert logs[2].arguments == [
            self.addon,
            another_pending_rejection,
            decision2,
        ]
        assert logs[2].user == self.user

        # All pending rejections flags in the past should have been dropped
        # when the rejection was applied (there are no other pending rejections
        # in this test).
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection__isnull=False
        ).exists()
        # The pending_rejection_by should also have been cleared.
        assert not VersionReviewerFlags.objects.filter(
            pending_rejection_by__isnull=False
        ).exists()
        # And pending_content_rejection too
        assert not VersionReviewerFlags.objects.filter(
            pending_content_rejection__isnull=False
        ).exists()

        assert len(mail.outbox) == 2
        assert 'right to appeal' in mail.outbox[0].body
        assert 'right to appeal' in mail.outbox[1].body

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
            addon=self.addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.0',
        )
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


class TestAutoRejectTransactions(AutoRejectTestsMixin, TransactionTestCase):
    def test_full_run(self):
        # Addon with a couple versions including its current_version pending
        # rejection, the add-on should be rejected with the versions
        all_pending_rejection = self.addon
        version = version_factory(
            addon=all_pending_rejection, version='0.9', created=self.days_ago(42)
        )
        version_review_flags_factory(version=version, pending_rejection=self.yesterday)
        # Add-on with an old version pending rejection, but a newer one
        # approved: only the old one should be rejected.
        old_pending_rejection = addon_factory(
            version_kw={'version': '10.0', 'created': self.days_ago(2)}
        )
        version_review_flags_factory(
            version=old_pending_rejection.current_version,
            pending_rejection=self.yesterday,
        )
        new_version_old_pending_rejection = version_factory(
            addon=old_pending_rejection, version='11.0'
        )
        # One with an old version approved, but a newer one pending
        # rejection: only the newer one should be rejected.
        new_pending_rejection = addon_factory(
            version_kw={'version': '20.0', 'created': self.days_ago(3)}
        )
        new_pending_rejection_new_version = version_factory(
            addon=new_pending_rejection, version='21.0', created=self.days_ago(2)
        )
        version_review_flags_factory(
            version=new_pending_rejection_new_version, pending_rejection=self.yesterday
        )
        # Add-on with a version pending rejection in the future, it shouldn't
        # be touched yet.
        future_pending_rejection = addon_factory()
        version_review_flags_factory(
            version=future_pending_rejection.current_version,
            pending_rejection=datetime.now() + timedelta(days=2),
        )
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
            old_pending_rejection.current_version == new_version_old_pending_rejection
        )
        assert new_version_old_pending_rejection.is_public()
        assert (
            not old_pending_rejection.versions.filter(version='10.0').get().is_public()
        )

        # Third one should still be public, only its newer version rejected.
        new_pending_rejection.refresh_from_db()
        new_pending_rejection_new_version.refresh_from_db()
        assert new_pending_rejection.is_public()
        assert (
            new_pending_rejection.current_version != new_pending_rejection_new_version
        )
        assert not new_pending_rejection_new_version.is_public()
        assert new_pending_rejection.versions.filter(version='20.0').get().is_public()

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
            pending_rejection__lt=now
        ).exists()

        assert len(mail.outbox) == 2
        assert 'right to appeal' in mail.outbox[0].body
        assert 'right to appeal' in mail.outbox[1].body


@freeze_time(backfill_reviewactionreasons_for_delayed_rejections.Command.MAX_DATE)
class TestBackfillReviewactionreasonsForDelayedRejections(TestCase):
    def check_log(self, alog, reasons, policies):
        alog.reload()
        assert sorted(
            alog.reviewactionreasonlog_set.values_list('reason', flat=True)
        ) == [reason.id for reason in reasons]
        assert sorted(
            alog.cinderpolicylog_set.values_list('cinder_policy', flat=True)
        ) == [policy.id for policy in policies]
        for reason in reasons:
            assert ReviewActionReason(id=reason.id) in alog.arguments
        for policy in policies:
            assert CinderPolicy(id=policy.id) in alog.arguments

    def check_decision(self, decision, policies):
        assert list(decision.policies.all()) == policies

    def _test_basic(self, delayed_activity_class, after_activity_class):
        # basic case - a rejection that didn't have any reasons, that was preceeded by a
        # delayed rejection
        addon = addon_factory()
        version_1 = addon.current_version
        version_2 = version_factory(addon=addon)
        user = user_factory()

        policy_1 = CinderPolicy.objects.create(uuid='1', name='the policy')
        policy_2 = CinderPolicy.objects.create(uuid='2', name='another policy')
        warning_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON, addon=addon
        )
        warning_decision.policies.set((policy_1,))
        reason_1 = ReviewActionReason.objects.create(
            name='the reason', canned_response='why', cinder_policy=policy_1
        )
        reason_2 = ReviewActionReason.objects.create(
            name='another reason',
            canned_response='why!?',
        )
        ActivityLog.objects.create(
            delayed_activity_class,
            addon,
            version_1,
            reason_1,
            policy_1,
            warning_decision,
            user=user,
        )
        ActivityLog.objects.create(
            delayed_activity_class,
            addon,
            version_2,
            reason_2,
            policy_2,
            warning_decision,
            user=user,
        )
        override_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=addon,
            override_of=warning_decision,
        )
        rejected = ActivityLog.objects.create(
            after_activity_class,
            addon,
            version_1,
            version_2,
            override_decision,
            user=user,
        )

        call_command('backfill_reviewactionreasons_for_delayed_rejections')

        self.check_log(rejected, [reason_1, reason_2], [policy_1, policy_2])
        self.check_decision(override_decision, [policy_1, policy_2])

    def test_basic_content_rejection(self):
        self._test_basic(
            amo.LOG.REJECT_CONTENT_DELAYED,
            amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED,
        )

    def test_basic_code_rejection(self):
        self._test_basic(
            amo.LOG.REJECT_VERSION_DELAYED,
            amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED,
        )

    def test_multiple_rejections(self):
        # A more complex case - there are multiple rejections, but we only want the one
        # that immediately preceeded the expiration
        addon = addon_factory()
        user = user_factory()
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)
        three_days_ago = today - timedelta(days=3)

        # this is a previous rejection -possibly cancelled- so should be ignored
        ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            addon,
            addon.current_version,
            ReviewActionReason.objects.create(name='previous', canned_response='hmm'),
            CinderPolicy.objects.create(uuid='3', name='previous policy'),
            user=user,
            created=three_days_ago,
        )
        policy = CinderPolicy.objects.create(uuid='1', name='the policy')
        warning_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON, addon=addon
        )
        warning_decision.policies.set((policy,))
        reason = ReviewActionReason.objects.create(
            name='the reason', canned_response='why', cinder_policy=policy
        )
        ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            addon,
            addon.current_version,
            reason,
            policy,
            warning_decision,
            user=user,
            created=two_days_ago,
        )
        override_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=addon,
            override_of=warning_decision,
        )
        rejected = ActivityLog.objects.create(
            amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED,
            addon,
            addon.current_version,
            override_decision,
            user=user,
            created=yesterday,
        )
        # this is *after* the expiration, so should be ignored
        ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED,
            addon,
            addon.current_version,
            ReviewActionReason.objects.create(name='another', canned_response='hmm'),
            CinderPolicy.objects.create(uuid='2', name='another policy'),
            user=user,
            created=today,
        )

        call_command('backfill_reviewactionreasons_for_delayed_rejections')

        self.check_log(rejected, [reason], [policy])
        self.check_decision(override_decision, [policy])

    def test_too_old_and_too_new(self):
        addon = addon_factory()
        version = addon.current_version
        user = user_factory()
        date_within = (
            backfill_reviewactionreasons_for_delayed_rejections.Command.MAX_DATE
        )
        date_after = date_within + timedelta(minutes=1)
        date_before = (
            backfill_reviewactionreasons_for_delayed_rejections.Command.MIN_DATE
            - timedelta(minutes=1)
        )

        policy = CinderPolicy.objects.create(uuid='1', name='the policy')
        warning_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON, addon=addon
        )
        warning_decision.policies.set((policy,))
        reason = ReviewActionReason.objects.create(
            name='the reason', canned_response='why', cinder_policy=policy
        )
        with freeze_time(date_after):
            delayed = ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                addon,
                version,
                reason,
                policy,
                warning_decision,
                user=user,
            )
            override_decision = ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
                addon=addon,
                override_of=warning_decision,
            )
            rejected = ActivityLog.objects.create(
                amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED,
                addon,
                version,
                override_decision,
                user=user,
            )

        call_command('backfill_reviewactionreasons_for_delayed_rejections')
        self.check_log(rejected, [], [])
        self.check_decision(override_decision, [])

        delayed.update(created=date_before)
        rejected.update(created=date_before)
        CinderPolicyLog.objects.update(created=date_before)
        ReviewActionReasonLog.objects.update(created=date_before)
        call_command('backfill_reviewactionreasons_for_delayed_rejections')
        self.check_log(rejected, [], [])
        self.check_decision(override_decision, [])

        delayed.update(created=date_within)
        rejected.update(created=date_within)
        CinderPolicyLog.objects.update(created=date_within)
        ReviewActionReasonLog.objects.update(created=date_within)
        call_command('backfill_reviewactionreasons_for_delayed_rejections')
        self.check_log(rejected, [reason], [policy])
        self.check_decision(override_decision, [policy])
