from django.conf import settings
from django.core import mail
from django.urls import reverse

from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.core import set_user
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview

from ..models import AbuseReport, CinderDecision, CinderJob, CinderPolicy
from ..utils import (
    CinderActionApproveInitialDecision,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionOverrideApprove,
    CinderActionRejectVersion,
    CinderActionRejectVersionDelayed,
    CinderActionTargetAppealApprove,
    CinderActionTargetAppealRemovalAffirmation,
)


class BaseTestCinderAction:
    def setUp(self):
        addon = addon_factory()
        self.decision = CinderDecision.objects.create(
            cinder_id='ab89',
            action=DECISION_ACTIONS.AMO_APPROVE,
            notes='extra notes',
            addon=addon,
        )
        self.cinder_job = CinderJob.objects.create(
            job_id='1234', decision=self.decision
        )
        self.decision.policies.add(
            CinderPolicy.objects.create(
                uuid='1234',
                name='Bad policy',
                text='This is bad thing',
                parent=CinderPolicy.objects.create(
                    uuid='p4r3nt',
                    name='Parent Policy',
                    text='Parent policy text',
                ),
            )
        )
        self.abuse_report_no_auth = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=addon.guid,
            cinder_job=self.cinder_job,
            reporter_email='email@domain.com',
        )
        self.abuse_report_auth = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=addon.guid,
            cinder_job=self.cinder_job,
            reporter=user_factory(),
        )
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        # It's the webhook's responsibility to do this before calling the
        # action. We need it for the ActivityLog creation to work.
        set_user(self.task_user)

    def _test_reporter_takedown_email(self, subject):
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[1].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert mail.outbox[1].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert 'have therefore removed' in mail.outbox[0].body
        assert 'have therefore removed' in mail.outbox[1].body
        assert 'appeal' not in mail.outbox[0].body
        assert 'appeal' not in mail.outbox[1].body
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[1].body
        assert 'After reviewing' not in mail.outbox[0].body
        assert 'After reviewing' not in mail.outbox[0].body
        assert '&quot;' not in mail.outbox[0].body
        assert '&quot;' not in mail.outbox[1].body
        assert '&lt;b&gt;' not in mail.outbox[0].body
        assert '&lt;b&gt;' not in mail.outbox[1].body

    def _test_reporter_ignore_email(self, subject):
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[1].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert mail.outbox[1].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert 'does not violate Mozilla' in mail.outbox[0].body
        assert 'does not violate Mozilla' in mail.outbox[1].body
        assert 'was correct' not in mail.outbox[0].body
        assert (
            reverse(
                'abuse.appeal_reporter',
                kwargs={
                    'abuse_report_id': self.abuse_report_no_auth.id,
                    'decision_cinder_id': self.decision.cinder_id,
                },
            )
            in mail.outbox[0].body
        )
        assert (
            reverse(
                'abuse.appeal_reporter',
                kwargs={
                    'abuse_report_id': self.abuse_report_auth.id,
                    'decision_cinder_id': self.decision.cinder_id,
                },
            )
            in mail.outbox[1].body
        )
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[1].body
        assert '&quot;' not in mail.outbox[0].body
        assert '&quot;' not in mail.outbox[1].body
        assert '&lt;b&gt;' not in mail.outbox[0].body
        assert '&lt;b&gt;' not in mail.outbox[1].body

    def _test_reporter_appeal_takedown_email(self, subject):
        assert mail.outbox[0].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert 'have removed' in mail.outbox[0].body
        assert 'right to appeal' not in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[0].body
        assert 'After reviewing' in mail.outbox[0].body
        assert '&quot;' not in mail.outbox[0].body
        assert '&lt;b&gt;' not in mail.outbox[0].body

    def _test_reporter_ignore_appeal_email(self, subject):
        assert mail.outbox[0].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert 'does not violate Mozilla' in mail.outbox[0].body
        assert 'right to appeal' not in mail.outbox[0].body
        assert 'was correct' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[0].body
        assert '&quot;' not in mail.outbox[0].body
        assert '&lt;b&gt;' not in mail.outbox[0].body

    def _check_owner_email(self, mail_item, subject, snippet):
        user = getattr(self, 'user', getattr(self, 'author', None))
        assert mail_item.to == [user.email]
        assert mail_item.subject == subject + ' [ref:ab89]'
        assert snippet in mail_item.body
        assert '[ref:ab89]' in mail_item.body
        assert '&quot;' not in mail_item.body
        assert '&lt;b&gt;' not in mail_item.body

    def _test_owner_takedown_email(self, subject, snippet):
        mail_item = mail.outbox[-1]
        self._check_owner_email(mail_item, subject, snippet)
        assert 'right to appeal' in mail_item.body
        assert (
            reverse(
                'abuse.appeal_author',
                kwargs={
                    'decision_cinder_id': self.decision.cinder_id,
                },
            )
            in mail_item.body
        )
        assert (
            '\n        - Parent Policy, specifically Bad policy: This is bad thing\n'
            in mail_item.body
        )
        assert '&quot;' not in mail_item.body
        assert '&lt;b&gt;' not in mail_item.body

    def _test_owner_affirmation_email(
        self, subject, additional_reasoning='extra notes.'
    ):
        mail_item = mail.outbox[0]
        self._check_owner_email(mail_item, subject, 'was correct')
        assert 'right to appeal' not in mail_item.body
        if additional_reasoning:
            assert additional_reasoning in mail_item.body
        else:
            assert ' was correct. Based on that determination' in mail_item.body
        if isinstance(self.decision.target, Addon):
            # Verify we used activity mail for Addon related target emails
            log_token = ActivityLogToken.objects.get()
            assert log_token.uuid.hex in mail_item.reply_to[0]

    def _test_owner_restore_email(self, subject):
        mail_item = mail.outbox[0]
        assert len(mail.outbox) == 1
        self._check_owner_email(mail_item, subject, 'we have restored')
        assert 'right to appeal' not in mail_item.body

    def _test_approve_appeal_or_override(CinderActionClass):
        raise NotImplementedError

    def test_approve_appeal_success(self):
        self._test_approve_appeal_or_override(CinderActionTargetAppealApprove)
        assert 'After reviewing your appeal' in mail.outbox[0].body

    def test_approve_override(self):
        self._test_approve_appeal_or_override(CinderActionOverrideApprove)
        assert 'After reviewing your appeal' not in mail.outbox[0].body

    def test_reporter_ignore_report(self):
        subject = self._test_reporter_ignore_initial_or_appeal()
        assert len(mail.outbox) == 2
        self._test_reporter_ignore_email(subject)

    def test_reporter_ignore_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                addon=self.decision.addon,
                user=self.decision.user,
                rating=self.decision.rating,
                collection=self.decision.collection,
                action=DECISION_ACTIONS.AMO_APPROVE,
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        self.cinder_job.reload()
        subject = self._test_reporter_ignore_initial_or_appeal()
        assert len(mail.outbox) == 1  # only abuse_report_auth reporter
        self._test_reporter_ignore_appeal_email(subject)

    def test_owner_ignore_report_email(self):
        # This isn't called by cinder actions, because
        # CinderActionApproveInitialDecision.process_action returns (False, None),
        # but could be triggered by reviewer actions
        subject = self._test_reporter_ignore_initial_or_appeal(send_owner_email=True)
        assert len(mail.outbox) == 3
        self._test_reporter_ignore_email(subject)
        assert 'has been approved' in mail.outbox[-1].body

    def test_notify_reporters_reporters_provided(self):
        action = self.ActionClass(self.decision)
        action.notify_reporters(reporter_abuse_reports=[self.abuse_report_no_auth])
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[0].subject.endswith(
            f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert 'have therefore removed' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body


class TestCinderActionUser(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionBanUser

    def setUp(self):
        super().setUp()
        self.user = user_factory(display_name='<b>Bad Hørse</b>')
        self.cinder_job.abusereport_set.update(user=self.user, guid=None)
        self.decision.update(addon=None, user=self.user)

    def _test_ban_user(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        assert action.process_action() is None

        self.user.reload()
        self.assertCloseToNow(self.user.banned)
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_BANNED.id)
        assert activity.arguments == [self.user]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.user.name}'
        self._test_owner_takedown_email(subject, 'has been suspended')
        return subject

    def test_ban_user(self):
        subject = self._test_ban_user()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_ban_user_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                user=self.user, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_ban_user()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_ignore_initial_or_appeal(self, *, send_owner_email=None):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.decision)
        assert action.process_action() is None

        self.user.reload()
        assert not self.user.banned
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        if send_owner_email:
            action.notify_owners()
        return f'Mozilla Add-ons: {self.user.name}'

    def _test_approve_appeal_or_override(self, CinderActionClass):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        self.user.update(banned=self.days_ago(1), deleted=True)
        action = CinderActionClass(self.decision)
        assert action.process_action() is None

        self.user.reload()
        assert not self.user.banned
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_UNBAN.id)
        assert activity.arguments == [self.user]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.user.name}')

    def test_target_appeal_decline(self):
        self.user.update(banned=self.days_ago(1), deleted=True)
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.user.reload()
        assert self.user.banned
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.user.name}')


@override_switch('enable-cinder-reviewer-tools-integration', active=True)
class TestCinderActionAddon(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDisableAddon

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.addon = addon_factory(users=(self.author,), name='<b>Bad Addön</b>')
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)
        self.decision.update(addon=self.addon)

    def _test_disable_addon(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        action = self.ActionClass(self.decision)
        activity = action.process_action()
        assert activity
        assert activity.log == amo.LOG.FORCE_DISABLE
        assert self.addon.reload().status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        assert activity.arguments == [self.addon]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently disabled')
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        return subject

    def test_disable_addon(self):
        subject = self._test_disable_addon()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_disable_addon_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_disable_addon()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_approve_appeal_or_override(self, CinderActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = CinderActionClass(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.FORCE_ENABLE.id)
        assert activity.arguments == [self.addon]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def _test_reporter_ignore_initial_or_appeal(self, *, send_owner_email=None):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0
        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        if send_owner_email:
            action.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def test_escalate_addon(self):
        listed_version = self.addon.current_version
        listed_version.file.update(is_signed=True)
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        ActivityLog.objects.all().delete()
        action = CinderActionEscalateAddon(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert (
            listed_version.reload().needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert (
            unlisted_version.reload().needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_CINDER.id
        ).get()
        assert activity.arguments == [listed_version, unlisted_version]
        assert activity.user == self.task_user

        # but if we have a version specified, we flag that version
        NeedsHumanReview.objects.all().delete()
        other_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        assert not other_version.due_date
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(addon_version=other_version.version)
        assert action.process_action() is None
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.reload().needshumanreview_set.exists()
        other_version.reload()
        assert other_version.due_date
        assert (
            other_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.NEEDS_HUMAN_REVIEW_CINDER.id)
        assert activity.arguments == [other_version]
        assert activity.user == self.task_user
        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        assert len(mail.outbox) == 0

    def test_escalate_addon_no_versions_to_flag(self):
        listed_version = self.addon.current_version
        listed_version.file.update(is_signed=True)
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASON_CINDER_ESCALATION, version=listed_version
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASON_CINDER_ESCALATION, version=unlisted_version
        )
        assert NeedsHumanReview.objects.count() == 2
        ActivityLog.objects.all().delete()

        action = CinderActionEscalateAddon(self.decision)
        assert action.process_action() is None
        assert NeedsHumanReview.objects.count() == 2
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

    @override_switch('enable-cinder-reviewer-tools-integration', active=False)
    def test_escalate_addon_waffle_switch_off(self):
        # Escalation when the waffle switch is off is essentially a no-op on
        # AMO side.
        listed_version = self.addon.current_version
        listed_version.file.update(is_signed=True)
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        ActivityLog.objects.all().delete()
        action = CinderActionEscalateAddon(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not listed_version.due_date
        assert not unlisted_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.due_date
        assert ActivityLog.objects.count() == 0

        other_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        assert not other_version.due_date
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(addon_version=other_version.version)
        assert action.process_action() is None
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.reload().needshumanreview_set.exists()
        other_version.reload()
        assert not other_version.due_date
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.reload().needshumanreview_set.exists()

    def test_target_appeal_decline(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_target_appeal_decline_no_additional_reasoning(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        self.decision.update(notes='')
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: {self.addon.name}', additional_reasoning=None
        )

    def test_notify_owners_with_manual_policy_block(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        self.ActionClass(self.decision).notify_owners(
            policy_text='some other policy justification'
        )
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert 'right to appeal' in mail_item.body
        assert (
            reverse(
                'abuse.appeal_author',
                kwargs={
                    'decision_cinder_id': self.decision.cinder_id,
                },
            )
            in mail_item.body
        )
        assert 'Bad policy: This is bad thing' not in mail_item.body
        assert 'some other policy justification' in mail_item.body

    def test_notify_owners_with_for_third_party_decision(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert 'right to appeal' in mail_item.body
        assert 'in an assessment performed on our own initiative' not in mail_item.body
        assert 'based on a report we received from a third party' in mail_item.body

    def test_notify_owners_with_for_proactive_decision(self):
        self.cinder_job.delete()
        self.abuse_report_auth.delete()
        self.abuse_report_no_auth.delete()
        self.decision.refresh_from_db()
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert 'right to appeal' in mail_item.body
        assert 'in an assessment performed on our own initiative' in mail_item.body
        assert 'based on a report we received from a third party' not in mail_item.body

    def _test_reject_version(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        action = CinderActionRejectVersion(self.decision)
        # note: process_action isn't implemented for this action currently.

        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 0
        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners(extra_context={'version_list': '2.3, 3.45'})
        mail_item = mail.outbox[-1]
        self._check_owner_email(mail_item, subject, 'have been disabled')

        assert 'right to appeal' in mail_item.body
        assert (
            reverse(
                'abuse.appeal_author',
                kwargs={
                    'decision_cinder_id': self.decision.cinder_id,
                },
            )
            in mail_item.body
        )
        assert 'Bad policy: This is bad thing' in mail_item.body
        assert 'Affected versions: 2.3, 3.45' in mail_item.body
        return subject

    def test_reject_version(self):
        subject = self._test_reject_version()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_reject_version_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_reject_version()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reject_version_delayed(self):
        self.decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
        )
        action = CinderActionRejectVersionDelayed(self.decision)
        # note: process_action isn't implemented for this action currently.

        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 0
        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners(
            extra_context={
                'version_list': '2.3, 3.45',
                'delayed_rejection_days': 66,
            }
        )
        mail_item = mail.outbox[-1]
        user = getattr(self, 'user', getattr(self, 'author', None))
        assert mail_item.to == [user.email]
        assert mail_item.subject == (f'{subject} [ref:{self.decision.cinder_id}]')
        assert 'will be disabled' in mail_item.body
        assert f'[ref:{self.decision.cinder_id}]' in mail_item.body

        assert 'right to appeal' not in mail_item.body
        assert 'Bad policy: This is bad thing' in mail_item.body
        assert 'Affected versions: 2.3, 3.45' in mail_item.body
        assert '66 day(s)' in mail_item.body
        return subject

    def test_reject_version_delayed(self):
        subject = self._test_reject_version_delayed()
        assert len(mail.outbox) == 3
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[1].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject
            + f' [ref:{self.decision.cinder_id}/'
            + f'{self.abuse_report_no_auth.id}]'
        )
        assert mail.outbox[1].subject == (
            subject + f' [ref:{self.decision.cinder_id}/{self.abuse_report_auth.id}]'
        )
        assert 'we will remove' in mail.outbox[0].body
        assert 'we will remove' in mail.outbox[1].body
        assert 'right to appeal' not in mail.outbox[0].body
        assert 'right to appeal' not in mail.outbox[1].body
        assert (
            f'[ref:{self.decision.cinder_id}/{self.abuse_report_no_auth.id}]'
            in mail.outbox[0].body
        )
        assert (
            f'[ref:{self.decision.cinder_id}/{self.abuse_report_auth.id}]'
            in mail.outbox[1].body
        )

    def test_reject_version_delayed_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=self.addon
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_reject_version_delayed()
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:{self.decision.cinder_id}/{self.abuse_report_auth.id}]'
        )
        assert 'we will remove' in mail.outbox[0].body
        assert 'right to appeal' not in mail.outbox[0].body
        assert (
            f'[ref:{self.decision.cinder_id}/{self.abuse_report_auth.id}]'
            in mail.outbox[0].body
        )


class TestCinderActionCollection(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDeleteCollection

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.collection = collection_factory(
            author=self.author,
            name='<b>Bad Collectiôn</b>',
            slug='bad-collection',
        )
        self.cinder_job.abusereport_set.update(collection=self.collection, guid=None)
        self.decision.update(addon=None, collection=self.collection)

    def _test_delete_collection(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action = self.ActionClass(self.decision)
        log_entry = action.process_action()

        assert self.collection.reload()
        assert self.collection.deleted
        assert self.collection.slug
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_DELETED.id)
        assert activity == log_entry
        assert activity.arguments == [self.collection]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.collection.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_delete_collection(self):
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_delete_collection_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                collection=self.collection, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_ignore_initial_or_appeal(self, *, send_owner_email=None):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.decision)
        assert action.process_action() is None

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        if send_owner_email:
            action.notify_owners()
        return f'Mozilla Add-ons: {self.collection.name}'

    def _test_approve_appeal_or_override(self, CinderActionClass):
        self.collection.update(deleted=True)
        action = CinderActionClass(self.decision)
        assert action.process_action() is None

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_UNDELETED.id)
        assert activity.arguments == [self.collection]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_target_appeal_decline(self):
        self.collection.update(deleted=True)
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.collection.reload()
        assert self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.collection.name}')


class TestCinderActionRating(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDeleteRating

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.rating = Rating.objects.create(
            addon=addon_factory(), user=self.author, body='Saying something <b>bad</b>'
        )
        self.cinder_job.abusereport_set.update(rating=self.rating, guid=None)
        self.decision.update(addon=None, rating=self.rating)
        ActivityLog.objects.all().delete()

    def _test_delete_rating(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action = self.ActionClass(self.decision)
        assert action.process_action() is None

        assert self.rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.DELETE_RATING.id)
        assert activity.arguments == [self.rating.addon, self.rating]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        subject = f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_delete_rating(self):
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_delete_rating_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=CinderDecision.objects.create(
                rating=self.rating, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(
            cinder_job=original_job, appellant_job=self.cinder_job
        )
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_ignore_initial_or_appeal(self, *, send_owner_email=None):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.decision)
        assert action.process_action() is None

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        if send_owner_email:
            action.notify_owners()
        return f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'

    def _test_approve_appeal_or_override(self, CinderActionClass):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = CinderActionClass(self.decision)
        assert action.process_action() is None

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.UNDELETE_RATING.id)
        assert activity.arguments == [self.rating, self.rating.addon]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_restore_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def test_target_appeal_decline(self):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.rating.reload()
        assert self.rating.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        action.notify_reporters(
            reporter_abuse_reports=self.cinder_job.get_reporter_abuse_reports(),
            is_appeal=self.cinder_job.is_appeal,
        )
        action.notify_owners()
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )
