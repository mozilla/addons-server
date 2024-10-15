from datetime import datetime

from django.conf import settings
from django.core import mail
from django.urls import reverse

from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import RECOMMENDED
from olympia.core import set_user
from olympia.ratings.models import Rating

from ..models import AbuseReport, CinderAppeal, CinderDecision, CinderJob, CinderPolicy
from ..utils import (
    CinderActionApproveInitialDecision,
    CinderActionApproveNoAction,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionIgnore,
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
            notes="extra note's",
            addon=addon,
            action_date=datetime.now(),
        )
        self.cinder_job = CinderJob.objects.create(
            job_id='1234', decision=self.decision
        )
        self.policy = CinderPolicy.objects.create(
            uuid='1234',
            name='Bad policy',
            text='This is bad thing',
            parent=CinderPolicy.objects.create(
                uuid='p4r3nt',
                name='Parent Policy',
                text='Parent policy text',
            ),
        )
        self.decision.policies.add(self.policy)
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
        assert self.decision.notes not in mail.outbox[0].body
        assert self.decision.notes not in mail.outbox[1].body

    def _test_reporter_content_approve_email(self, subject):
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
        assert self.decision.notes not in mail.outbox[0].body
        assert self.decision.notes not in mail.outbox[1].body

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
        assert self.decision.notes not in mail.outbox[0].body

    def _test_reporter_appeal_approve_email(self, subject):
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
        assert '&#x27;' not in mail.outbox[0].body
        assert self.decision.notes in mail.outbox[0].body

    def _check_owner_email(self, mail_item, subject, snippet):
        user = getattr(self, 'user', getattr(self, 'author', None))
        assert mail_item.to == [user.email]
        assert mail_item.subject == subject + ' [ref:ab89]'
        assert snippet in mail_item.body
        assert '[ref:ab89]' in mail_item.body
        assert '&quot;' not in mail_item.body
        assert '&lt;b&gt;' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.notes in mail_item.body

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
            '\n    - Parent Policy, specifically Bad policy: This is bad thing\n'
            in mail_item.body
        )
        assert '&quot;' not in mail_item.body
        assert '&lt;b&gt;' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.notes in mail_item.body

    def _test_owner_affirmation_email(self, subject):
        mail_item = mail.outbox[0]
        self._check_owner_email(mail_item, subject, 'was correct')
        assert 'right to appeal' not in mail_item.body
        notes = f'{self.decision.notes}. ' if self.decision.notes else ''
        assert f' was correct. {notes}Based on that determination' in (mail_item.body)
        assert '&#x27;' not in mail_item.body
        if isinstance(self.decision.target, Addon):
            # Verify we used activity mail for Addon related target emails
            log_token = ActivityLogToken.objects.get()
            assert log_token.uuid.hex in mail_item.reply_to[0]

    def _test_owner_restore_email(self, subject):
        mail_item = mail.outbox[0]
        assert len(mail.outbox) == 1
        self._check_owner_email(mail_item, subject, 'we have restored')
        assert 'right to appeal' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.notes in mail_item.body

    def _test_approve_appeal_or_override(CinderActionClass):
        raise NotImplementedError

    def test_approve_appeal_success(self):
        self._test_approve_appeal_or_override(CinderActionTargetAppealApprove)
        assert 'After reviewing your appeal' in mail.outbox[0].body

    def test_approve_override(self):
        self._test_approve_appeal_or_override(CinderActionOverrideApprove)
        assert 'After reviewing your appeal' not in mail.outbox[0].body

    def _test_reporter_no_action_taken(
        self,
        *,
        ActionClass=CinderActionApproveNoAction,
        action=DECISION_ACTIONS.AMO_APPROVE,
    ):
        raise NotImplementedError

    def test_reporter_content_approve_report(self):
        subject = self._test_reporter_no_action_taken()
        assert len(mail.outbox) == 2
        self._test_reporter_content_approve_email(subject)

    def test_reporter_appeal_approve(self):
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        self.cinder_job.reload()
        subject = self._test_reporter_no_action_taken()
        assert len(mail.outbox) == 1  # only abuse_report_auth reporter
        self._test_reporter_appeal_approve_email(subject)

    def test_owner_content_approve_report_email(self):
        # This isn't called by cinder actions, but is triggered by reviewer actions
        subject = self._test_reporter_no_action_taken(
            ActionClass=CinderActionApproveInitialDecision
        )
        assert len(mail.outbox) == 3
        self._test_reporter_content_approve_email(subject)
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

    def test_reporter_ignore_invalid_report(self):
        self.decision.policies.first().update()
        subject = self._test_reporter_no_action_taken(
            ActionClass=CinderActionIgnore, action=DECISION_ACTIONS.AMO_IGNORE
        )
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[1].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert mail.outbox[1].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[1].body

        for idx in range(0, 1):
            assert 'were unable to identify a violation' in mail.outbox[idx].body
            assert 'right to appeal' not in mail.outbox[idx].body
            assert 'This is bad thing' in mail.outbox[idx].body  # policy text
            assert 'Bad policy' not in mail.outbox[idx].body  # policy name
            assert 'Parent' not in mail.outbox[idx].body  # parent policy text

    def test_email_content_not_escaped(self):
        unsafe_str = '<script>jar=window.triggerExploit();"</script>'
        self.decision.update(notes=unsafe_str)
        action = self.ActionClass(self.decision)
        action.notify_owners()
        assert unsafe_str in mail.outbox[0].body

        action = CinderActionApproveNoAction(self.decision)
        mail.outbox.clear()
        action.notify_reporters(
            reporter_abuse_reports=[self.abuse_report_auth], is_appeal=True
        )
        assert unsafe_str in mail.outbox[0].body


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
        activity = action.process_action()
        assert activity.log == amo.LOG.ADMIN_USER_BANNED
        assert ActivityLog.objects.count() == 1
        assert activity.arguments == [self.user, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.notes,
            'cinder_action': DECISION_ACTIONS.AMO_BAN_USER,
        }

        self.user.reload()
        self.assertCloseToNow(self.user.banned)
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_ban_user()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(
        self,
        *,
        ActionClass=CinderActionApproveNoAction,
        action=DECISION_ACTIONS.AMO_APPROVE,
    ):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        self.user.reload()
        assert not self.user.banned
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.user.name}')

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        self.user.update(email='superstarops@mozilla.com')
        assert action.should_hold_action() is True

        self.user.update(email='foo@baa')
        assert action.should_hold_action() is False
        del self.user.groups_list
        self.grant_permission(self.user, 'this:thing')
        assert action.should_hold_action() is True

        self.user.groups_list = []
        assert action.should_hold_action() is False
        addon = addon_factory(users=[self.user])
        assert action.should_hold_action() is False
        self.make_addon_promoted(addon, RECOMMENDED, approve_version=True)
        assert action.should_hold_action() is True

        self.user.banned = datetime.now()
        assert action.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_ADMIN_USER_BANNED
        assert ActivityLog.objects.count() == 1
        assert activity.arguments == [self.user, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.notes,
            'cinder_action': DECISION_ACTIONS.AMO_BAN_USER,
        }


@override_switch('dsa-cinder-forwarded-review', active=True)
@override_switch('dsa-appeals-review', active=True)
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

        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def _test_reporter_no_action_taken(
        self,
        *,
        ActionClass=CinderActionApproveNoAction,
        action=DECISION_ACTIONS.AMO_APPROVE,
    ):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def test_target_appeal_decline(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_target_appeal_decline_no_manual_reasoning_text(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        self.decision.update(notes='')
        action = CinderActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self.decision.update(notes='')
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_notify_owners_with_manual_reasoning_text(self):
        self.decision.update(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            notes='some other policy justification',
        )
        self.ActionClass(self.decision).notify_owners(extra_context={'policies': ()})
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

    def test_notify_owners_non_public_url(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        self.addon.update(status=amo.STATUS_DISABLED, _current_version=None)
        assert self.addon.get_url_path() == ''

        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert '/firefox/' not in mail_item.body
        assert (
            f'{settings.SITE_URL}/en-US/developers/addon/{self.addon.id}/'
            in mail_item.body
        )

    def _test_reject_version(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        action = CinderActionRejectVersion(self.decision)
        # process_action isn't implemented for this action currently.
        with self.assertRaises(NotImplementedError):
            action.process_action()

        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
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
        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
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

    def test_notify_owner_with_appeal_waffle_off_doesnt_offer_appeal(self):
        self.cinder_job.delete()
        self.decision.refresh_from_db()
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        assert not self.decision.is_third_party_initiated

        with override_switch('dsa-appeals-review', active=True):
            self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert 'right to appeal' in mail_item.body
        mail.outbox.clear()

        with override_switch('dsa-appeals-review', active=False):
            self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', 'permanently disabled'
        )
        assert 'right to appeal' not in mail_item.body


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

        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(
        self,
        *,
        ActionClass=CinderActionApproveNoAction,
        action=DECISION_ACTIONS.AMO_APPROVE,
    ):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
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
        activity = action.process_action()
        assert activity.log == amo.LOG.DELETE_RATING
        assert ActivityLog.objects.count() == 1
        assert activity.arguments == [self.rating, self.policy, self.rating.addon]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.notes,
            'cinder_action': DECISION_ACTIONS.AMO_DELETE_RATING,
            'addon_id': self.rating.addon_id,
            'addon_title': str(self.rating.addon.name),
            'body': self.rating.body,
            'is_flagged': False,
        }

        assert self.rating.reload().deleted
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
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
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(
        self,
        *,
        ActionClass=CinderActionApproveNoAction,
        action=DECISION_ACTIONS.AMO_APPROVE,
    ):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        AddonUser.objects.create(addon=self.rating.addon, user=self.rating.user)
        assert action.should_hold_action() is False
        self.make_addon_promoted(self.rating.addon, RECOMMENDED, approve_version=True)
        assert action.should_hold_action() is False
        self.rating.update(
            reply_to=Rating.objects.create(
                addon=self.rating.addon, user=user_factory(), body='original'
            )
        )
        assert action.should_hold_action() is True

        self.rating.update(deleted=self.rating.id)
        assert action.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_DELETE_RATING
        assert ActivityLog.objects.count() == 1
        assert activity.arguments == [self.rating, self.policy, self.rating.addon]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.notes,
            'cinder_action': DECISION_ACTIONS.AMO_DELETE_RATING,
        }
