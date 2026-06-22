import json
import uuid
from datetime import date, datetime, timedelta
from inspect import isclass
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.test.utils import override_settings
from django.urls import reverse

import responses
from waffle.testutils import override_switch

import olympia.abuse.actions
from olympia import amo
from olympia.access.models import Group
from olympia.activity.models import (
    ActivityLog,
    ActivityLogToken,
    AttachmentLog,
)
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
)
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.models import Block, BlocklistSubmission, BlockVersion
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.blocklist import BlockReason, BlockType
from olympia.constants.permissions import ADDONS_HIGH_IMPACT_APPROVE
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.core import set_user
from olympia.files.models import File
from olympia.promoted.models import PromotedGroup
from olympia.ratings.models import Rating
from olympia.reviewers.models import AutoApprovalSummary, NeedsHumanReview
from olympia.versions.models import VersionReviewerFlags

from ..actions import (
    ContentAction,
    ContentActionApproveListingContent,
    ContentActionApproveVersion,
    ContentActionBanUser,
    ContentActionBlockAddon,
    ContentActionDelayedMidHardBlockAddon,
    ContentActionDelayedShortSoftBlockAddon,
    ContentActionDeleteCollection,
    ContentActionDeleteRating,
    ContentActionDisableAddon,
    ContentActionForwardToLegal,
    ContentActionIgnore,
    ContentActionLegalTakedownDisableAddon,
    ContentActionRejectListingContent,
    ContentActionRejectVersion,
    ContentActionRejectVersionDelayed,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from ..models import (
    AbuseReport,
    CinderAppeal,
    CinderJob,
    CinderPolicy,
    ContentDecision,
    ContentDecisionFollowupAction,
)


class BaseContentActionMixin:
    def setUp(self):
        addon = addon_factory()
        self.past_negative_decision = ContentDecision.objects.create(
            cinder_id='4815162342',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon,
            action_date=datetime.now(),
        )
        self.decision = ContentDecision.objects.create(
            cinder_id='ab89',
            action=self.default_decision_action,
            private_notes="extra note's",
            reasoning='some réasoning',
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

    def _check_owner_email(self, mail_item, subject, snippet):
        user = getattr(self, 'user', getattr(self, 'author', None))
        assert mail_item.to == [user.email]
        assert mail_item.subject == subject + ' [ref:ab89]'
        assert snippet in mail_item.body
        assert '[ref:ab89]' in mail_item.body
        assert '&quot;' not in mail_item.body
        assert '&lt;b&gt;' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.reasoning in mail_item.body
        assert self.decision.private_notes not in mail_item.body

    def test_log_action_user(self):
        # just an arbitrary activity class
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        assert (
            self.ActionClass(self.decision).log_action(amo.LOG.ADMIN_USER_UNBAN).user
            == reviewer
        )

    def test_log_action_saves_policy_texts(self):
        # Update the policy with a placeholder - these aren't supposed to be
        # used with Cinder originated policy decisions, but we should handle
        # this gracefully.
        self.policy.update(text='This is {JUDGEMENT} thing')
        assert self.ActionClass(self.decision).log_action(
            amo.LOG.ADMIN_USER_UNBAN
        ).details['policy_texts'] == [
            'Parent Policy, specifically Bad policy: This is  thing'
        ]
        # change the decision to one that was made by an AMO reviewer
        self.decision.update(reviewer_user=user_factory())
        assert (
            # no policy text - the text will be included in the decision notes
            'policy_texts'
            not in self.ActionClass(self.decision)
            .log_action(amo.LOG.ADMIN_USER_UNBAN)
            .details
        )

        # except if the review has directly specified the policies with the placeholders
        self.decision.update(
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    self.policy.uuid: {'JUDGEMENT': 'a Térrible'}
                }
            }
        )
        assert self.ActionClass(self.decision).log_action(
            amo.LOG.ADMIN_USER_UNBAN
        ).details['policy_texts'] == [
            'Parent Policy, specifically Bad policy: This is a Térrible thing'
        ]

    def test_email_content_not_escaped(self):
        unsafe_str = '<script>jar=window.triggerExploit();"</script>'
        self.decision.update(reasoning=unsafe_str)
        action_helper = self.ActionClass(self.decision)
        action_helper.notify_owners()
        assert unsafe_str in mail.outbox[0].body

        action_helper = ContentActionApproveListingContent(self.decision)
        mail.outbox.clear()
        action_helper.notify_reporters(
            reporter_abuse_reports=[self.abuse_report_auth], is_appeal=True
        )
        assert unsafe_str in mail.outbox[0].body

    def test_should_be_skipped_by_automation(self):
        # should_be_skipped_by_automation is a classmethod, default is to
        # return False.
        assert not self.ActionClass.should_be_skipped_by_automation()


class NegativeContentActionMixin:
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
        assert self.decision.reasoning not in mail.outbox[0].body
        assert self.decision.reasoning not in mail.outbox[1].body
        assert self.decision.private_notes not in mail.outbox[0].body
        assert self.decision.private_notes not in mail.outbox[1].body

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
        assert self.decision.reasoning not in mail.outbox[0].body
        assert self.decision.private_notes not in mail.outbox[0].body

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
        assert self.decision.reasoning in mail_item.body
        assert self.decision.private_notes not in mail_item.body

    def _test_owner_affirmation_email(self, subject, should_allow_uploads=False):
        mail_item = mail.outbox[0]
        self._check_owner_email(mail_item, subject, 'not provide sufficient basis')
        assert 'right to appeal' not in mail_item.body
        notes = f'{self.decision.reasoning}. ' if self.decision.reasoning else ''
        assert f' policies. {notes}Based on that determination' in (mail_item.body)
        assert '&#x27;' not in mail_item.body
        if isinstance(self.decision.target, Addon):
            # Verify we used activity mail for Addon related target emails
            log_token = ActivityLogToken.objects.get()
            assert log_token.uuid.hex in mail_item.reply_to[0]
        if should_allow_uploads:
            assert 'If you submit a new version' in mail_item.body
        else:
            assert 'If you submit a new version' not in mail_item.body

    def _test_owner_restore_email(self, subject, *, fragment='we have restored'):
        mail_item = mail.outbox[0]
        assert len(mail.outbox) == 1
        self._check_owner_email(mail_item, subject, fragment)
        assert 'right to appeal' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.reasoning in mail_item.body
        assert self.decision.private_notes not in mail_item.body

    def _test_approve_appeal_or_override(self, ActionClass):
        # Common things that we expect to happen after a successful appeal or
        # override of a negative action.
        raise NotImplementedError

    def _reverse_appeal_or_override(self, ActionClass):
        """Carry out the reversal that an appeal or an override triggers and
        return ``(activity, action_helper)``.

        For an appeal this is the dedicated ContentActionTargetAppealApprove
        helper's process_action. For an override (reverse-then-apply) the
        previous action is reversed via ContentDecision.reverse_overridden_action
        and the action helper is the one for the new action."""
        if self.decision.override_of_id:
            activity = self.decision.reverse_overridden_action()
            return activity, self.decision.get_action_helper()
        action_helper = ActionClass(self.decision)
        return action_helper.process_action(), action_helper

    def test_approve_appeal_success(self):
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)
        assert 'After reviewing your appeal' in mail.outbox[0].body

    def test_approve_override_success(self):
        # An override that reverses a takedown applies the new action (here a
        # plain approval). The previous action is reversed (see the per-class
        # _test_approve_appeal_or_override), but - unlike an appeal - no restore
        # email is sent: only the new action notifies (and approving a restored
        # target sends no owner email).
        self.decision.update(
            override_of=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self._test_approve_appeal_or_override(None)
        assert len(mail.outbox) == 0

    def test_notify_reporters_reporters_provided(self):
        action_helper = self.ActionClass(self.decision)
        action_helper.notify_reporters(
            reporter_abuse_reports=[self.abuse_report_no_auth]
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[0].subject.endswith(
            f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert 'have therefore removed' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body

    def test_notify_2nd_level_approvers(self):
        self.ActionClass(self.decision).notify_2nd_level_approvers()
        assert len(mail.outbox) == 0

        user = user_factory()
        self.grant_permission(user, ':'.join(ADDONS_HIGH_IMPACT_APPROVE))
        self.ActionClass(self.decision).notify_2nd_level_approvers()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            'A new item has entered the second level approval queue'
        )
        assert mail.outbox[0].to == [user.email]
        assert reverse('reviewers.decision_review', args=[self.decision.id]) in (
            mail.outbox[0].body
        )


class PositiveContentActionMixin:
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
        assert self.decision.reasoning not in mail.outbox[0].body
        assert self.decision.reasoning not in mail.outbox[1].body
        assert self.decision.private_notes not in mail.outbox[0].body
        assert self.decision.private_notes not in mail.outbox[1].body

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
        assert self.decision.reasoning in mail.outbox[0].body
        assert self.decision.private_notes not in mail.outbox[0].body

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        raise NotImplementedError

    def _test_reporter_content_approved_action_taken(self):
        # For most ActionClasses, there is no action taken.
        return self._test_reporter_no_action_taken(
            ActionClass=ContentActionApproveListingContent,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )

    def test_reporter_ignore_invalid_report(self):
        self.decision.policies.first().update()
        subject = self._test_reporter_no_action_taken(
            ActionClass=ContentActionIgnore, action=DECISION_ACTIONS.AMO_IGNORE
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


class TestContentActionBanUser(
    PositiveContentActionMixin,
    NegativeContentActionMixin,
    BaseContentActionMixin,
    TestCase,
):
    ActionClass = ContentActionBanUser
    default_decision_action = DECISION_ACTIONS.AMO_BAN_USER

    def setUp(self):
        super().setUp()
        self.user = user_factory(display_name='<b>Bad Hørse</b>')
        self.cinder_job.abusereport_set.update(user=self.user, guid=None)
        self.decision.update(addon=None, user=self.user)
        self.past_negative_decision.update(
            addon=None, user=self.user, action=self.default_decision_action
        )

    def _test_ban_user(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        activity = action_helper.process_action()
        assert activity.log == amo.LOG.ADMIN_USER_BANNED
        assert activity.arguments == [self.user, self.decision, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.user, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}

        self.user.reload()
        self.assertCloseToNow(self.user.banned)
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        subject = f'Mozilla Add-ons: {self.user.name}'
        self._test_owner_takedown_email(subject, 'has been suspended')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(private_notes='', action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        action_helper.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_ban_user(self):
        subject = self._test_ban_user()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_already_banned(self):
        self.user.update(banned=self.days_ago(42))
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_ban_user_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                user=self.user, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_ban_user()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action_helper = ActionClass(self.decision)
        assert action_helper.process_action() is None

        self.user.reload()
        assert not self.user.banned
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.user.name}'

    def _test_approve_appeal_or_override(self, ActionClass):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        self.user.update(banned=self.days_ago(1), deleted=True)
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        self.user.reload()
        assert not self.user.banned
        assert activity.log == amo.LOG.ADMIN_USER_UNBAN
        assert activity.arguments == [self.user, self.decision, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.user, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(f'Mozilla Add-ons: {self.user.name}')

    def test_target_appeal_decline(self):
        self.user.update(banned=self.days_ago(1), deleted=True)
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.user.reload()
        assert self.user.banned
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.user.name}')

    def test_should_hold_action(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        self.user.update(email='superstarops@mozilla.com')
        assert action_helper.should_hold_action() is True

        self.user.update(email='foo@baa')
        assert action_helper.should_hold_action() is False
        del self.user.groups_list
        self.grant_permission(self.user, 'this:thing')
        assert action_helper.should_hold_action() is True

        self.user.groups_list = []
        assert action_helper.should_hold_action() is False
        addon = addon_factory(users=[self.user])
        assert action_helper.should_hold_action() is False
        self.make_addon_promoted(addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action_helper.should_hold_action() is True

        self.user.banned = datetime.now()
        assert action_helper.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_ADMIN_USER_BANNED
        assert activity.arguments == [self.user, self.decision, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.user, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}


@override_switch('dsa-cinder-forwarded-review', active=True)
class TestContentActionDisableAddon(
    NegativeContentActionMixin, BaseContentActionMixin, TestCase
):
    ActionClass = ContentActionDisableAddon
    activity_log_action = amo.LOG.FORCE_DISABLE
    disable_snippet = 'permanently disabled'
    default_decision_action = DECISION_ACTIONS.AMO_DISABLE_ADDON

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.addon = addon_factory(users=(self.author,), name='<b>Bad Addön</b>')
        self.old_version = self.addon.current_version
        self.version = version_factory(addon=self.addon)
        self.another_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        self.addon.reload()
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)
        self.decision.update(addon=self.addon)
        self.decision.target_versions.set((self.version, self.old_version))
        self.past_negative_decision.update(
            addon=self.addon, action=self.default_decision_action
        )
        self.past_negative_decision.target_versions.set(
            (self.version, self.old_version)
        )

    def test_addon_version_has_target_versions(self):
        # if the decision has target_versions, then the most recent target
        # version is used.
        # Approve another_version, making it the new current version, it should
        # not make it the addon_version on the ContentAction, because it's not
        # in target_versions.
        self.another_version.file.update(status=amo.STATUS_APPROVED)
        assert self.version != self.addon.current_version
        assert self.ActionClass(self.decision).addon_version == self.version

        # If we add it to the target_versions, then it will become the
        # addon_version because it's the last one.
        self.decision.target_versions.add(self.another_version)
        assert self.ActionClass(self.decision).addon_version == self.another_version

    def test_addon_version_has_no_target_version(self):
        # If there is no target_versions we default to the current_version...
        self.decision.target_versions.clear()
        assert (
            self.ActionClass(self.decision).addon_version == self.addon.current_version
        )
        # ... but if there is no current_version we use the latest version,
        # regardless of status.
        File.objects.update(status=amo.STATUS_DISABLED)
        self.addon.update_version()
        assert not self.addon.current_version
        assert self.ActionClass(self.decision).addon_version == self.another_version

    def _process_action_and_notify(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        activity = action_helper.process_action()
        assert activity
        assert activity.log == self.activity_log_action
        assert self.addon.reload().status == amo.STATUS_DISABLED
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() >= 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).first()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()

    def test_log_action_no_notes(self):
        self.decision.update(private_notes='', action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        action_helper.process_action()
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_taken_down(self):
        self.decision.update(action=self.default_decision_action)
        self.addon.update(status=amo.STATUS_DISABLED)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_execute_action(self):
        self._process_action_and_notify()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        assert len(mail.outbox) == 3
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled
        assert flags.auto_approval_disabled_unlisted
        self._test_reporter_takedown_email(subject)

    def test_execute_action_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        self._process_action_and_notify()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_approve_appeal_or_override(self, ActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert activity.log == amo.LOG.FORCE_ENABLE
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_target_appeal_decline(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_target_appeal_decline_no_manual_reasoning_text(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        self.decision.update(reasoning='')
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self.decision.update(reasoning='')
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_notify_owners_with_manual_reasoning_text(self):
        self.decision.update(
            action=self.default_decision_action,
            reasoning='some other policy justification',
        )
        self.ActionClass(self.decision).notify_owners(
            extra_context={'policy_texts': ()}
        )
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', self.disable_snippet
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
        self.decision.update(action=self.default_decision_action)
        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', self.disable_snippet
        )
        assert 'right to appeal' in mail_item.body
        assert 'in an assessment performed on our own initiative' not in mail_item.body
        assert 'based on a report we received from a third party' in mail_item.body

    def test_notify_owners_with_for_proactive_decision(self):
        self.cinder_job.delete()
        self.abuse_report_auth.delete()
        self.abuse_report_no_auth.delete()
        self.decision.refresh_from_db()
        self.decision.update(action=self.default_decision_action)
        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', self.disable_snippet
        )
        assert 'right to appeal' in mail_item.body
        assert 'in an assessment performed on our own initiative' in mail_item.body
        assert 'based on a report we received from a third party' not in mail_item.body

    def test_notify_owners_non_public_url(self):
        self.decision.update(action=self.default_decision_action)
        self.addon.update(status=amo.STATUS_DISABLED, _current_version=None)
        assert self.addon.get_url_path() == ''

        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', self.disable_snippet
        )
        assert '/firefox/' not in mail_item.body
        assert (
            f'{settings.SITE_URL}/en-US/developers/addon/{self.addon.id}/'
            in mail_item.body
        )

    def test_should_hold_action(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action_helper.should_hold_action() is True

        self.addon.status = amo.STATUS_DISABLED
        assert action_helper.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_FORCE_DISABLE
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'versions': [self.version.version, self.old_version.version],
            'human_review': False,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}

        user = user_factory()
        self.decision.update(reviewer_user=user)
        activity = action_helper.hold_action()
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'versions': [self.version.version, self.old_version.version],
            'human_review': True,
            **(
                {
                    'policy_texts': [self.policy.full_text()],
                }
                if not self.decision.has_policy_text_in_comments
                else {}
            ),
        }
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled
        assert flags.auto_approval_disabled_unlisted

    def test_forward_from_reviewers_no_job(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_LEGAL_FORWARD, cinder_job=None)
        action_helper = ContentActionForwardToLegal(self.decision)
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}v1/create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        action_helper.process_action()

        assert CinderJob.objects.get(job_id='1234-xyz')
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body['reasoning'] == self.decision.reasoning
        assert request_body['queue_slug'] == 'legal-escalations'

    def test_forward_from_reviewers_with_job(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_LEGAL_FORWARD)
        action_helper = ContentActionForwardToLegal(self.decision)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}v1/jobs/{self.cinder_job.job_id}/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}v1/create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        action_helper.process_action()

        new_cinder_job = CinderJob.objects.get(job_id='1234-xyz')
        assert new_cinder_job != self.cinder_job
        assert new_cinder_job.job_id == '1234-xyz'
        # The reports should now be part of the new job instead
        assert self.abuse_report_auth.reload().cinder_job == new_cinder_job
        assert self.abuse_report_no_auth.reload().cinder_job == new_cinder_job
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body['reasoning'] == self.decision.reasoning
        assert request_body['queue_slug'] == 'legal-escalations'
        assert not new_cinder_job.resolvable_in_reviewer_tools

    def test_log_action_args(self):
        activity = self.ActionClass(self.decision).log_action(self.activity_log_action)
        assert self.addon in activity.arguments
        assert self.version in activity.arguments
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.details == {
            'versions': [self.version.version, self.old_version.version],
            'human_review': False,
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }

    def test_log_action_human_review(self):
        assert (
            self.ActionClass(self.decision)
            .log_action(self.activity_log_action)
            .details['human_review']
            is False
        )

        self.decision.update(reviewer_user=self.task_user)
        assert (
            self.ActionClass(self.decision)
            .log_action(self.activity_log_action)
            .details['human_review']
            is False
        )

        self.decision.update(reviewer_user=user_factory())
        assert (
            self.ActionClass(self.decision)
            .log_action(self.activity_log_action)
            .details['human_review']
            is True
        )

    def test_log_action_attachment_moved(self):
        # Set up an unlikely scenario, where there a multiple activity logs, and more
        # than one attachment. Because AttachmentLog.activity_log is a OneToOne field we
        # choose the latest instance.
        # note: Purposely calling ContentAction log_action to set up these logs
        first = ContentAction.log_action(
            self.ActionClass(self.decision), self.activity_log_action
        )
        AttachmentLog.objects.create(
            activity_log=first,
            file=ContentFile('Pseudo File', name='first.txt'),
        )
        ContentAction.log_action(
            self.ActionClass(self.decision), self.activity_log_action
        )
        third = ContentAction.log_action(
            self.ActionClass(self.decision), self.activity_log_action
        )
        attachmentlog = AttachmentLog.objects.create(
            activity_log=third,
            file=ContentFile('Other File', name='third.txt'),
        )

        new_activity = self.ActionClass(self.decision).log_action(
            self.activity_log_action
        )
        assert new_activity.attachmentlog == attachmentlog

    def _test_approve_appeal_or_override_but_listing_rejected(self, ActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_REJECTED
        assert activity.log == amo.LOG.FORCE_ENABLE
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 3
        second_activity = (
            ActivityLog.objects.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CHANGE_STATUS.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: {self.addon.name}', fragment='remains unavailable'
            )

    def test_approve_appeal_success_but_listing_rejected(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override_but_listing_rejected(
            ContentActionTargetAppealApprove
        )
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body
        assert self.addon.reload().status == amo.STATUS_REJECTED

    def test_approve_override_success_but_listing_rejected(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        self.decision.update(
            override_of=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self._test_approve_appeal_or_override_but_listing_rejected(None)
        # The reversal re-enabled the add-on but the separately-rejected listing
        # content is not restored by the reversal, and no restore email is sent.
        assert len(mail.outbox) == 0
        assert self.addon.reload().status == amo.STATUS_REJECTED

    def _test_approve_appeal_or_override_but_not_approved(self, ActionClass):
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_DISABLED)

        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_NOMINATED
        assert activity.log == amo.LOG.FORCE_ENABLE
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 3
        second_activity = (
            ActivityLog.objects.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CHANGE_STATUS.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: {self.addon.name}',
                fragment='information on its availability',
            )

    def test_approve_appeal_success_but_not_approved(self):
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override_but_not_approved(
            ContentActionTargetAppealApprove
        )

    def test_approve_override_success_but_not_approved(self):
        self.decision.update(
            override_of=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self._test_approve_appeal_or_override_but_not_approved(None)
        assert len(mail.outbox) == 0


class TestContentActionRejectVersion(TestContentActionDisableAddon):
    ActionClass = ContentActionRejectVersion
    activity_log_action = amo.LOG.REJECT_VERSION
    disable_snippet = 'versions of your Extension have been disabled'
    default_decision_action = DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON

    def setUp(self):
        super().setUp()
        # Set up another_version as approved so that the rejection of the other
        # 2 versions leaves one version approved and the add-on stays public.
        self.another_version.file.update(status=amo.STATUS_APPROVED)

    def _test_reject_version(self, *, content_review, expected_emails_from_action=0):
        old_version_original_status = self.old_version.file.status
        version_original_status = self.version.file.status
        self.decision.update(
            action=self.default_decision_action,
            metadata={'content_review': content_review},
        )
        NeedsHumanReview(version=self.old_version).save(_no_automatic_activity_log=True)
        NeedsHumanReview(version=self.version).save(_no_automatic_activity_log=True)
        action_helper = ContentActionRejectVersion(self.decision)
        # process_action is only available for reviewer tools decisions.
        with self.assertRaises(NotImplementedError):
            action_helper.process_action()

        # but with a reviewer attached to the decision we can proceed
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        activity = action_helper.process_action()
        assert activity
        assert (
            activity.log == amo.LOG.REJECT_CONTENT
            if content_review
            else amo.LOG.REJECT_VERSION
        )
        assert self.addon.reload().status == amo.STATUS_APPROVED
        for version, original_status in (
            (self.old_version, old_version_original_status),
            (self.version, version_original_status),
        ):
            assert version.file.reload().status == amo.STATUS_DISABLED
            assert version.file.original_status == original_status
            version_flags = VersionReviewerFlags.objects.filter(version=version).get()
            assert version_flags.pending_rejection is None
            assert version_flags.pending_rejection_by is None
            assert version_flags.pending_content_rejection is None
            assert not version.needshumanreview_set.filter(is_active=True).exists()
            self.assertCloseToNow(version.reload().human_review_date)
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.decision.reviewer_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.decision.reviewer_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == expected_emails_from_action
        subject = f'Mozilla Add-ons: {self.addon.name}'

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners(extra_context={'version_list': '2.3, 3.45'})
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

    def _test_approve_appeal_or_override(
        self, ActionClass, *, fragment='we have restored'
    ):
        self.old_version.file.update(
            status=amo.STATUS_DISABLED, original_status=amo.STATUS_APPROVED
        )
        # set-up where version.file doesn't have an original_status for some reason
        self.version.file.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        # safe fallback to AWAITING_REVIEW when original_status not defined
        assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        # but otherwise should restore the original status
        assert self.old_version.file.reload().status == amo.STATUS_APPROVED
        assert activity.log == amo.LOG.UNREJECT_VERSION
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: {self.addon.name}', fragment=fragment
            )

    def test_approve_appeal_success_but_listing_rejected(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override(
            ContentActionTargetAppealApprove, fragment='we have re-enabled'
        )
        assert self.addon.reload().status == amo.STATUS_REJECTED
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body

    def test_approve_override_success_but_listing_rejected(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        self.decision.update(
            override_of=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self._test_approve_appeal_or_override(None)
        # The reversal un-rejected the versions but didn't restore the
        # separately-rejected listing content, and sent no restore email.
        assert len(mail.outbox) == 0
        assert self.addon.reload().status == amo.STATUS_REJECTED

    def test_approve_override_success_for_delayed_reject(self):
        for version in self.past_negative_decision.target_versions.all():
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now(),
                pending_rejection_by=self.task_user,
                pending_content_rejection=False,
            )
        self.past_negative_decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
        )
        self.decision.update(
            override_of=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.old_version.file.update(status=amo.STATUS_APPROVED)
        ActivityLog.objects.all().delete()
        activity = self.decision.reverse_overridden_action()

        assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        assert self.old_version.file.reload().status == amo.STATUS_APPROVED
        assert self.version.reviewerflags.reload().pending_rejection is None
        assert self.old_version.reviewerflags.reload().pending_rejection is None
        assert activity.log == amo.LOG.CLEAR_PENDING_REJECTION
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == 0

    def test_log_action_no_notes(self):
        self.decision.update(
            private_notes='',
            action=self.default_decision_action,
            reviewer_user=user_factory(),
        )
        action_helper = self.ActionClass(self.decision)
        action_helper.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_taken_down(self):
        self.decision.update(
            action=self.default_decision_action, reviewer_user=user_factory()
        )
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_already_taken_down_delayed_rejection(self):
        in_the_future = datetime.now() + timedelta(days=14, hours=1)
        self.decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            metadata={
                'delayed_rejection_date': in_the_future.isoformat(),
                'content_review': True,
            },
            reviewer_user=user_factory(),
        )
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_already_delayed_rejected_delayed_rejection(self):
        in_the_future = datetime.now() + timedelta(days=14, hours=1)
        self.decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            metadata={
                'delayed_rejection_date': in_the_future.isoformat(),
                'content_review': True,
            },
            reviewer_user=user_factory(),
        )
        for version in (self.version, self.old_version):
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=in_the_future,
                pending_rejection_by=self.decision.reviewer_user,
                pending_content_rejection=True,
            )
        action_helper = ContentActionRejectVersionDelayed(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_already_delayed_different_review_type_rejected_delayed_rejection(self):
        in_the_future = datetime.now() + timedelta(days=14, hours=1)
        for version in (self.version, self.old_version):
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=in_the_future,
                pending_rejection_by=user_factory(),
                pending_content_rejection=True,
            )
        self.test_execute_action_delayed()

    def test_already_partially_disabled(self):
        # If only one version is disabled, the rejection is applied and
        # recorded normally.
        self.version.file.update(status=amo.STATUS_DISABLED)
        subject = self._test_reject_version(content_review=False)
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_already_partially_disabled_delayed_rejection(self):
        # If only one version is disabled, the delayed rejection is applied and
        # recorded normally.
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.test_execute_action_delayed()

    def test_already_taken_down_by_developer(self):
        # If versions were disabled by the developer, that doesn't prevent the
        # rejection from being applied and recorded.
        self.version.is_user_disabled = True
        self.old_version.is_user_disabled = True
        ActivityLog.objects.all().delete()
        subject = self._test_reject_version(content_review=False)
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_already_taken_down_by_developer_delayed_rejection(self):
        # If versions were disabled by the developer, that doesn't prevent the
        # delayed rejection from being applied and recorded.
        self.version.is_user_disabled = True
        self.old_version.is_user_disabled = True
        ActivityLog.objects.all().delete()
        self.test_execute_action_delayed()

    def test_execute_action(self):
        subject = self._test_reject_version(content_review=False)
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert not flags.auto_approval_disabled
        assert not flags.auto_approval_disabled_unlisted
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_execute_action_unlisted(self):
        self.decision.target_versions.update(channel=amo.CHANNEL_UNLISTED)
        subject = self._test_reject_version(content_review=False)
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled_until_next_approval_unlisted
        assert not flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled
        assert not flags.auto_approval_disabled_unlisted
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_execute_action_both_channels(self):
        # Only make one of the two versions targeted unlisted.
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        subject = self._test_reject_version(content_review=False)
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_execute_action_content_review(self):
        subject = self._test_reject_version(content_review=True)
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_execute_action_with_stakeholder_email(self):
        stakeholder = user_factory()
        Group.objects.get(name=self.ActionClass.stakeholder_acl_group_name).users.add(
            stakeholder
        )
        self.version.file.update(is_signed=True)
        self.another_version.file.update(approval_date=datetime(2025, 2, 3))
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self._test_reject_version(content_review=False, expected_emails_from_action=1)
        assert len(mail.outbox) == 4
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'Rejection issued for {self.addon.name}'
        assert (
            f'{self.another_version.version} will be the new current version of the '
            'Extension; first approved 2025-02-03.' in mail.outbox[0].body
        )

    def test_execute_action_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_reject_version(content_review=False)
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reject_version_delayed(
        self,
        *,
        content_review,
        expected_emails_from_action=0,
        set_metadata=True,
        expected_delay_days=14,
    ):
        original_statuses = {
            version.file.pk: version.file.status
            for version in (self.old_version, self.version)
        }
        in_the_future = datetime.now() + timedelta(days=expected_delay_days, hours=1)
        if set_metadata:
            metadata = {
                'content_review': content_review,
                'delayed_rejection_date': in_the_future.isoformat(),
            }
        else:
            metadata = {}
        self.decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            metadata=metadata,
        )
        action_helper = ContentActionRejectVersionDelayed(self.decision)
        # process_action is only available for reviewer tools decisions.
        with self.assertRaises(NotImplementedError):
            action_helper.process_action()

        # but with a reviewer attached to the decision we can proceed
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        activity = action_helper.process_action()
        assert activity
        assert (
            activity.log == amo.LOG.REJECT_CONTENT_DELAYED
            if content_review
            else amo.LOG.REJECT_VERSION_DELAYED
        )
        assert self.addon.reload().status == amo.STATUS_APPROVED
        for version in (self.old_version, self.version):
            assert version.file.status == original_statuses.get(version.file.pk)
            version_flags = VersionReviewerFlags.objects.filter(version=version).get()
            self.assertCloseToNow(version_flags.pending_rejection, now=in_the_future)
            assert version_flags.pending_rejection_by == reviewer
            assert version_flags.pending_content_rejection == content_review
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.decision.reviewer_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.decision.reviewer_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == expected_emails_from_action
        subject = f'Mozilla Add-ons: {self.addon.name}'

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners(
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

    def test_execute_action_delayed(self, *, content_review=False):
        subject = self._test_reject_version_delayed(content_review=content_review)
        flags = self.addon.reviewerflags.reload()
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval
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

    def test_execute_action_content_review_delayed(self):
        self.test_execute_action_delayed(content_review=True)

    def test_execute_action_delayed_default_delay(self):
        self._test_reject_version_delayed(
            content_review=False,
            set_metadata=False,
            expected_delay_days=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
        )

    def test_execute_action_delayed_with_stakeholder_email(self):
        stakeholder = user_factory()
        Group.objects.get(name=self.ActionClass.stakeholder_acl_group_name).users.add(
            stakeholder
        )
        self.version.file.update(is_signed=True)
        self.another_version.file.update(approval_date=datetime(2025, 2, 3))
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self._test_reject_version_delayed(
            content_review=False, expected_emails_from_action=1
        )
        assert len(mail.outbox) == 4
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert (
            mail.outbox[0].subject
            == f'14 day delayed rejection issued for {self.addon.name}'
        )
        assert (
            f'{self.another_version.version} will be the new current version of the '
            'Extension; first approved 2025-02-03.' in mail.outbox[0].body
        )

    def test_execute_action_delayed_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                action=DECISION_ACTIONS.AMO_APPROVE, addon=self.addon
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_reject_version_delayed(content_review=False)
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

    def test_hold_action(self):
        NeedsHumanReview(version=self.old_version).save(_no_automatic_activity_log=True)
        NeedsHumanReview(version=self.version).save(_no_automatic_activity_log=True)
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_REJECT_VERSIONS
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert activity.details == {
            'comments': self.decision.reasoning,
            'versions': [self.version.version, self.old_version.version],
            'human_review': False,
            'policy_texts': [self.policy.full_text()],
        }
        flags = self.addon.reviewerflags.reload()
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled
        assert not flags.auto_approval_disabled_unlisted
        assert self.version.needshumanreview_set.filter(is_active=True).exists()
        assert self.version.reload().human_review_date is None
        assert self.old_version.needshumanreview_set.filter(is_active=True).exists()
        assert self.old_version.reload().human_review_date is None

    def test_hold_action_human(self):
        user = user_factory()
        NeedsHumanReview(version=self.old_version).save(_no_automatic_activity_log=True)
        NeedsHumanReview(version=self.version).save(_no_automatic_activity_log=True)
        self.decision.update(action=self.default_decision_action, reviewer_user=user)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'versions': [self.version.version, self.old_version.version],
            'human_review': True,
        }
        flags = self.addon.reviewerflags.reload()
        assert not flags.auto_approval_disabled_until_next_approval_unlisted
        assert flags.auto_approval_disabled_until_next_approval
        assert not flags.auto_approval_disabled
        assert not flags.auto_approval_disabled_unlisted
        assert not self.version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(self.version.reload().human_review_date)
        assert not self.old_version.needshumanreview_set.filter(is_active=True).exists()
        self.assertCloseToNow(self.old_version.reload().human_review_date)

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        self.version.file.update(is_signed=True)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self.decision.target_versions.add(self.another_version)
        assert self.decision.target_versions.filter(file__is_signed=True).exists()
        assert action_helper.should_hold_action() is True

        self.version.file.update(is_signed=False)
        self.decision = ContentDecision.objects.get(id=self.decision.id)
        assert not self.decision.target_versions.filter(file__is_signed=True).exists()
        assert action_helper.should_hold_action() is False

    def test_should_hold_action_some_versions_remain(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self.version.file.update(is_signed=True)

        # While there are more public listed versions that wouldn't be affected
        # the rejection can go through without being held.
        action_helper = self.ActionClass(self.decision)
        assert action_helper.remaining_public_listed_versions().exists()
        assert action_helper.should_hold_action() is False

        # If that last remaining version is unlisted, suddenly we do hold the
        # rejection - no public listed versions would remain if that went
        # through.
        self.another_version.update(channel=amo.CHANNEL_UNLISTED)
        assert not action_helper.remaining_public_listed_versions().exists()
        assert action_helper.should_hold_action() is True

        # If that last remaining version is listed but not public, then we have
        # to hold the rejection once more, since no public listed versions
        # would remain once again.
        self.another_version.update(channel=amo.CHANNEL_LISTED)
        self.another_version.file.update(status=amo.STATUS_DISABLED)
        assert not action_helper.remaining_public_listed_versions().exists()
        assert action_helper.should_hold_action() is True

        # If that version is public but pending rejection we still have to hold
        # the rejection.
        self.another_version.file.update(status=amo.STATUS_APPROVED)
        VersionReviewerFlags.objects.create(
            version=self.another_version,
            pending_rejection=datetime.now(),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        assert action_helper.remaining_public_listed_versions().exists()
        assert action_helper.should_hold_action() is True

    def test_target_appeal_decline(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.version.file.reload()
        assert self.version.file.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners(extra_context={'is_addon_enabled': True})
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: {self.addon.name}', should_allow_uploads=True
        )

    def test_notify_stakeholders(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        listed_version = self.version
        listed_version.file.update(is_signed=True)
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        Group.objects.get(name=self.ActionClass.stakeholder_acl_group_name).users.add(
            stakeholder
        )
        self.decision.update(private_notes='', reasoning='Bad things!')
        self.another_version.file.update(approval_date=datetime(2025, 1, 2))

        # the addon is not promoted
        assert self.addon.publicly_promoted_groups == []
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 0

        # make the addon promoted
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'teh reason issued for {self.addon.name}'
        assert 'Bad things!' in body
        assert 'Private notes:' not in body
        assert (
            f'teh reason for versions:\n'
            f'[Listed] {listed_version.version}\n'
            '[Unlisted] \n' in body
        )
        assert f'/review-listed/{self.addon.id}' in body
        assert f'/review-unlisted/{self.addon.id}' not in body
        assert self.addon.get_absolute_url() in body

        assert (
            f'{self.another_version.version} will be the new current version of the '
            'Extension; first approved 2025-01-02' in body
        )

        # an unlisted version should result in second link to the unlisted review page
        self.decision.target_versions.add(unlisted_version)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 2  # another email
        body = mail.outbox[1].body
        assert (
            'teh reason for versions:\n'
            f'[Listed] {listed_version.version}\n'
            f'[Unlisted] {unlisted_version.version}\n'
        ) in body
        assert f'/review-listed/{self.addon.id} | ' in body
        assert f'/review-unlisted/{self.addon.id}' in body
        assert (
            f'{self.another_version.version} will be the new current version of the '
            'Extension; first approved 2025-01-02.' in body
        )

        # if the listed version(s) affected are the last approved versions indicate that
        self.another_version.file.update(status=amo.STATUS_DISABLED)
        self.old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 3  # another email
        body = mail.outbox[2].body
        assert (
            'teh reason for versions:\n'
            f'[Listed] {listed_version.version}\n'
            f'[Unlisted] {unlisted_version.version}\n'
        ) in body
        assert 'The add-on will no longer be publicly viewable on AMO.' in body

        # if no listed versions are affected we don't mention about the current version
        self.decision.target_versions.set([unlisted_version])
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 4  # another email
        body = mail.outbox[3].body
        assert 'will be the current' not in body
        assert 'no longer' not in body

        # And check that if no versions were signed we don't send an email
        listed_version.file.update(is_signed=False)
        unlisted_version.file.update(is_signed=False)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 4

    def test_notify_stakeholders_with_private_notes(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        listed_version = self.version
        listed_version.file.update(is_signed=True)
        version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        Group.objects.get(name=self.ActionClass.stakeholder_acl_group_name).users.add(
            stakeholder
        )
        self.decision.update(private_notes='These are the private notes.')

        # make the addon promoted
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'teh reason issued for {self.addon.name}'
        assert 'Private notes:' in mail.outbox[0].body
        assert 'These are the private notes.' in mail.outbox[0].body

    def test_notify_stakeholders_with_policy_texts(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        listed_version = self.version
        listed_version.file.update(is_signed=True)
        version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        Group.objects.get(name=self.ActionClass.stakeholder_acl_group_name).users.add(
            stakeholder
        )
        self.policy.update(text='Some reason why we can`t do {THIS}.')
        self.decision.update(
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    self.policy.uuid: {'THIS': 'that'}
                }
            }
        )

        # make the addon promoted
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        action_helper.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'teh reason issued for {self.addon.name}'
        assert 'Policies:' in mail.outbox[0].body
        assert (
            'Parent Policy, specifically Bad policy: Some reason why we can`t do that.'
            in mail.outbox[0].body
        )

    def _test_approve_appeal_or_override_but_not_approved(self, ActionClass):
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        self.version.file.update(
            status=amo.STATUS_DISABLED, original_status=amo.STATUS_AWAITING_REVIEW
        )
        self.another_version.update(channel=amo.CHANNEL_UNLISTED)
        self.addon.update(status=amo.STATUS_NULL)
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_NOMINATED
        assert activity.log == amo.LOG.UNREJECT_VERSION
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 3
        second_activity = (
            ActivityLog.objects.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CHANGE_STATUS.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: {self.addon.name}',
                fragment='information on its availability',
            )


class TestContentActionBlockAddon(TestContentActionDisableAddon):
    ActionClass = ContentActionBlockAddon
    default_decision_action = DECISION_ACTIONS.AMO_BLOCK_ADDON

    def setUp(self):
        super().setUp()
        self.decision.update(
            reviewer_user=self.task_user,
            metadata={ContentDecision.POLICY_DYNAMIC_VALUES: {}},
        )
        self.past_negative_decision.update(
            reviewer_user=self.task_user,
            metadata={ContentDecision.POLICY_DYNAMIC_VALUES: {}},
        )
        block = Block.objects.create(addon=self.addon, updated_by=self.task_user)
        BlockVersion.objects.create(block=block, version=self.another_version)

    def _check_block_activity_logs(self, block_activity, block_version_activity):
        assert block_activity.log == amo.LOG.BLOCKLIST_BLOCK_EDITED
        assert block_activity.arguments == [
            self.addon,
            self.addon.guid,
            self.addon.block,
        ]
        assert block_activity.user == self.task_user

        assert block_version_activity.log == amo.LOG.BLOCKLIST_VERSION_SOFT_BLOCKED
        assert block_version_activity.arguments == [
            self.version,
            self.old_version,
            self.addon.block,
        ]
        assert block_version_activity.user == self.task_user

    def _process_action_and_notify(self):
        super()._process_action_and_notify()

        assert ActivityLog.objects.count() == 4
        block_activity = ActivityLog.objects.all()[3]
        block_version_activity = ActivityLog.objects.all()[2]
        self._check_block_activity_logs(block_activity, block_version_activity)
        assert self.version.blockversion
        assert self.old_version.blockversion
        assert (
            self.version.blockversion.auto_block_reason == BlockReason.FRAUD_DECEPTIVE
        )
        assert (
            self.old_version.blockversion.auto_block_reason
            == BlockReason.FRAUD_DECEPTIVE
        )

    def test_already_taken_down(self):
        """For a block action, this shouldn't affect the block, only the disable"""
        self.decision.update(action=self.default_decision_action)
        self.addon.update(status=amo.STATUS_DISABLED)
        File.objects.filter(version__addon=self.addon).update(
            status=amo.STATUS_DISABLED
        )
        action_helper = self.ActionClass(self.decision)
        assert (
            action_helper.process_action() is None
        )  # we don't have a disable activity
        assert ActivityLog.objects.count() == 2
        block_activity = ActivityLog.objects.all()[1]
        block_version_activity = ActivityLog.objects.all()[0]
        self._check_block_activity_logs(block_activity, block_version_activity)
        assert self.version.blockversion
        assert self.old_version.blockversion
        assert (
            self.version.blockversion.auto_block_reason == BlockReason.FRAUD_DECEPTIVE
        )
        assert (
            self.old_version.blockversion.auto_block_reason
            == BlockReason.FRAUD_DECEPTIVE
        )

    def test_already_blocked(self):
        self.decision.update(action=self.default_decision_action)
        BlockVersion.objects.create(block=self.addon.block, version=self.version)
        BlockVersion.objects.create(block=self.addon.block, version=self.old_version)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_should_hold_action(self):
        PromotedGroup.objects.get_or_create(
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED, high_profile=True
        )
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action_helper.should_hold_action() is True

        # if one version is not blocked we still hold the action
        BlockVersion.objects.create(block=self.addon.block, version=self.version)
        assert action_helper.should_hold_action() is True

        BlockVersion.objects.create(block=self.addon.block, version=self.old_version)
        assert action_helper.should_hold_action() is False

    def test_log_action_saves_policy_texts(self):
        # update the policy with a placeholder.
        self.policy.update(text='This is {JUDGEMENT} thing')
        self.decision.update(
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {
                    self.policy.uuid: {'JUDGEMENT': 'a Térrible'}
                }
            }
        )
        assert self.ActionClass(self.decision).log_action(
            amo.LOG.ADMIN_USER_UNBAN
        ).details['policy_texts'] == [
            'Parent Policy, specifically Bad policy: This is a Térrible thing'
        ]

    def test_should_be_skipped_by_automation(self):
        # ContentActionBlockAddon.should_be_skipped_by_automation() needs the
        # addon and version to be passed.
        assert not self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

        # Any successful appeal against negative decision on the add-on in the
        # past causes it to return True.
        appeal_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=CinderJob.objects.create(target_addon=self.addon),
        )
        original_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=appeal_decision.cinder_job,
        )
        assert self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

        original_decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        assert self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

        original_decision.update(action=DECISION_ACTIONS.AMO_BLOCK_ADDON)
        assert self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

    def test_should_be_skipped_by_automation_non_negative_appeal(self):
        appeal_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_IGNORE,
            cinder_job=CinderJob.objects.create(target_addon=self.addon),
        )
        ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            appeal_job=appeal_decision.cinder_job,
        )
        assert not self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

    def test_should_be_skipped_by_automation_unsuccessful_appeal(self):
        appeal_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            cinder_job=CinderJob.objects.create(target_addon=self.addon),
        )
        ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=appeal_decision.cinder_job,
        )
        assert not self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

    def test_should_be_skipped_by_automation_unresolved_appeal(self):
        appeal_job = CinderJob.objects.create(target_addon=self.addon)
        ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=appeal_job,
        )
        assert not self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )


class TestContentActionDelayedShortSoftBlockAddon(
    NegativeContentActionMixin, BaseContentActionMixin, TestCase
):
    ActionClass = ContentActionDelayedShortSoftBlockAddon
    default_decision_action = DECISION_ACTIONS.AMO_FU_DELAY_SHORT_SOFT_BLOCK_ADDON
    block_type = BlockType.SOFT_BLOCKED

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.addon = addon_factory(users=(self.author,), name='<b>Bad Addön</b>')
        self.old_version = self.addon.current_version
        self.existing_block = Block.objects.create(
            addon=self.addon, updated_by=self.task_user
        )
        BlockVersion.objects.create(
            block=self.existing_block,
            version=self.old_version,
            block_type=self.block_type,
        )
        self.version = version_factory(addon=self.addon)
        self.another_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        self.addon.reload()
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)
        self.decision.update(addon=self.addon)
        self.past_negative_decision.update(
            addon=self.addon, action=self.default_decision_action
        )
        self.past_negative_decision.target_versions.set(
            (self.version, self.old_version)
        )

    def _test_process_action(self, version_ids, followup_action):
        assert not BlocklistSubmission.objects.exists()
        action_helper = self.ActionClass(self.decision, followup_action)
        assert action_helper.action == self.default_decision_action
        action_helper.process_action()
        assert BlocklistSubmission.objects.count() == 1
        submission = BlocklistSubmission.objects.get()
        assert submission.input_guids == self.addon.guid
        assert submission.to_block == [
            {
                'id': self.existing_block.id,
                'guid': self.addon.guid,
                'average_daily_users': self.addon.average_daily_users,
            }
        ]
        assert submission.changed_version_ids == version_ids
        assert submission.block_type == self.block_type
        assert (
            submission.signoff_state == BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED
        )
        assert submission.updated_by == self.task_user
        assert submission.disable_addon is False
        assert submission.preserve_block_metadata is True
        assert submission.disable_versions is False
        assert submission.reason is None
        assert submission.auto_block_reason == BlockReason.FRAUD_DECEPTIVE
        self.assertCloseToNow(
            submission.delayed_until,
            now=datetime.now() + timedelta(days=self.ActionClass.delay_days),
        )
        assert submission.from_followup == followup_action

        action_helper.notify_owners()
        if followup_action:
            assert len(mail.outbox) == 1
            assert mail.outbox[0].to == [self.author.email]
            assert 'We previously notified you of our finding' in mail.outbox[0].body
            assert str(action_helper.block_type.user_label) in mail.outbox[0].body
        else:
            assert len(mail.outbox) == 0

    def test_process_action_standalone(self):
        # Note: this isn't currently a codepath that's possible - the class is only used
        # as a follow-up action.
        self.decision.update(action=self.default_decision_action)
        assert not self.decision.target_versions.exists()
        self._test_process_action([self.another_version.id, self.version.id], None)
        # shouldn't change the addon or version.file statues.
        assert self.addon.status != amo.STATUS_DISABLED
        assert self.version.file.status != amo.STATUS_DISABLED
        assert self.old_version.file.status != amo.STATUS_DISABLED

    def test_process_action_followup_from_disable_addon(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        followup = ContentDecisionFollowupAction.objects.create(
            decision=self.decision, action=self.default_decision_action
        )
        self.addon.update(status=amo.STATUS_DISABLED)
        # typically this _would_ be set, but it shouldn't be used anyway
        assert not self.decision.target_versions.exists()
        # we're expecting all the non-blocked versions to be blocked
        self._test_process_action([self.another_version.id, self.version.id], followup)
        assert 'additional enforcement actions will be taken' not in mail.outbox[0].body
        assert (
            f'Affected versions: {self.another_version.version}, {self.version.version}'
            in mail.outbox[0].body
        )

    def test_process_action_with_multiple_followups(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        followup = ContentDecisionFollowupAction.objects.create(
            decision=self.decision, action=self.default_decision_action
        )
        another_followup = ContentDecisionFollowupAction.objects.create(
            decision=self.decision,
            action=DECISION_ACTIONS.AMO_FU_DELAY_LONG_HARD_BLOCK_ADDON,
        )
        self.addon.update(status=amo.STATUS_DISABLED)
        # typically this _would_ be set, but it shouldn't be used anyway
        assert not self.decision.target_versions.exists()
        # we're expecting all the non-blocked versions to be blocked
        self._test_process_action([self.another_version.id, self.version.id], followup)
        email_body = mail.outbox[0].body
        assert 'additional enforcement actions will be taken' in email_body
        assert another_followup.description_with_eta in email_body
        future_date = date.today() + timedelta(days=28)
        assert f'days, on {future_date.strftime("%Y-%m-%d")}' in email_body
        assert (
            f'Affected versions: {self.another_version.version}, {self.version.version}'
            in email_body
        )

    def test_process_action_followup_from_reject_version(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        followup = ContentDecisionFollowupAction.objects.create(
            decision=self.decision, action=self.default_decision_action
        )
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        # we're setting it up as if ContentActionRejectVersion was rejecting version and
        # old_version, but not another_version.
        self.decision.target_versions.set((self.version, self.old_version))
        # but we expect the follow-up action to ignore old_version since it's already
        # blocked, (and another_version because it's not being rejected)
        self._test_process_action([self.version.id], followup)
        assert 'additional enforcement actions will be taken' not in mail.outbox[0].body
        assert f'Affected versions: {self.version.version}\n' in mail.outbox[0].body

    def test_primary_action_emails_mention_followups(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        followup = ContentDecisionFollowupAction.objects.create(
            decision=self.decision, action=self.default_decision_action
        )
        action_helper = ContentActionDisableAddon(self.decision)

        action_helper.notify_owners()

        email_body = mail.outbox[0].body
        future_date = date.today() + timedelta(days=self.ActionClass.delay_days)
        assert 'If you do not remediate ' in email_body
        assert followup.description_with_eta in email_body
        assert f'days, on {future_date.strftime("%Y-%m-%d")}' in email_body

    def _test_approve_appeal_or_override(self, ActionClass):
        yet_another_version = version_factory(addon=self.addon)
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        self.past_negative_decision.target_versions.set(
            (self.version, self.another_version)
        )
        BlockVersion.objects.create(
            block=self.existing_block,
            version=self.version,
            block_type=self.block_type,
        )
        BlocklistSubmission.objects.create(
            input_guids=self.addon.guid,
            block_type=self.block_type,
            updated_by_id=self.task_user.id,
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
            changed_version_ids=[self.another_version.id, yet_another_version.id],
            disable_addon=False,
            disable_versions=False,
            delayed_until=datetime.now() + timedelta(days=1),
            preserve_block_metadata=True,
        )
        assert (
            BlockVersion.objects.filter(
                block__guid=self.addon.guid, block_type=self.block_type
            )
            .exclude(version=self.old_version)
            .count()
            == 1
        )
        assert (
            BlocklistSubmission.objects.filter(input_guids=self.addon.guid).count() == 1
        )

        self._reverse_appeal_or_override(ActionClass)

        # Block was deleted
        assert (
            not BlockVersion.objects.filter(
                block__guid=self.addon.guid, block_type=self.block_type
            )
            .exclude(version=self.old_version)
            .exists()
        )
        # we didn't delete the blocklistsubmission
        assert (
            BlocklistSubmission.objects.filter(input_guids=self.addon.guid).count() == 1
        )
        # but modified it to remove the version
        assert BlocklistSubmission.objects.get().changed_version_ids == [
            yet_another_version.id
        ]

    def test_approve_appeal_success(self):
        self.past_negative_decision.update(
            appeal_job=self.cinder_job, action=self.default_decision_action
        )
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)
        # TODO: once we add support for emails, re-enable this?
        # assert 'After reviewing your appeal' in mail.outbox[0].body

    def test_approve_override_success(self):
        self.decision.update(override_of=self.past_negative_decision)
        self.past_negative_decision.update(action=self.default_decision_action)
        self._test_approve_appeal_or_override(None)
        # TODO: once we add support for emails, re-enable this?
        # assert 'After reviewing your appeal' not in mail.outbox[0].body

    def test_approve_appeal_success_followup(self):
        self.past_negative_decision.update(
            appeal_job=self.cinder_job, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        ContentDecisionFollowupAction.objects.create(
            decision=self.past_negative_decision,
            action=self.default_decision_action,
            action_date=datetime.now(),
        )
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)

    def test_approve_appeal_success_followup_with_multiple_followups(self):
        self.past_negative_decision.update(
            appeal_job=self.cinder_job, action=DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        ContentDecisionFollowupAction.objects.create(
            decision=self.past_negative_decision,
            action=self.default_decision_action,
            action_date=datetime.now(),
        )
        # These follow-up actions are redundant, but shouldn't cause errors.
        ContentDecisionFollowupAction.objects.create(
            decision=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_FU_DELAY_LONG_SOFT_BLOCK_ADDON,
            action_date=datetime.now(),
        )
        ContentDecisionFollowupAction.objects.create(
            decision=self.past_negative_decision,
            action=DECISION_ACTIONS.AMO_FU_DELAY_LONG_HARD_BLOCK_ADDON,
            action_date=datetime.now(),
        )
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)

    def test_approve_override_success_followup(self):
        self.decision.update(override_of=self.past_negative_decision)
        self.past_negative_decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        ContentDecisionFollowupAction.objects.create(
            decision=self.past_negative_decision,
            action=self.default_decision_action,
            action_date=datetime.now(),
        )
        self._test_approve_appeal_or_override(None)

    def test_email_content_not_escaped(self):
        # TODO: If/when we support emails we should implement this
        pass

    def test_description(self):
        assert self.ActionClass.description == (
            'Add-on versions will be Restricted, after 7 days'
        )


class TestContentActionDelayedMidHardBlockAddon(
    TestContentActionDelayedShortSoftBlockAddon
):
    ActionClass = ContentActionDelayedMidHardBlockAddon
    default_decision_action = DECISION_ACTIONS.AMO_FU_DELAY_MID_HARD_BLOCK_ADDON
    block_type = BlockType.BLOCKED

    def setUp(self):
        super().setUp()
        BlockVersion.objects.create(
            block=self.existing_block,
            version=self.another_version,
            block_type=BlockType.SOFT_BLOCKED,
        )

    def test_description(self):
        assert self.ActionClass.description == (
            'Add-on versions will be Blocked, after 14 days'
        )


class TestContentActionApproveListingContent(
    PositiveContentActionMixin, BaseContentActionMixin, TestCase
):
    ActionClass = ContentActionApproveListingContent
    default_decision_action = DECISION_ACTIONS.AMO_APPROVE
    activity_log_action = amo.LOG.APPROVE_LISTING_CONTENT

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.addon = addon_factory(users=(self.author,), name='<b>Bad Addön</b>')
        self.old_version = self.addon.current_version
        self.version = version_factory(addon=self.addon)
        self.another_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        self.addon.reload()
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)
        self.decision.update(addon=self.addon)
        self.decision.target_versions.set((self.version, self.old_version))
        self.past_negative_decision.update(
            addon=self.addon, action=self.default_decision_action
        )
        self.past_negative_decision.target_versions.set(
            (self.version, self.old_version)
        )

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action_helper = ActionClass(self.decision)
        assert action_helper.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def _test_reporter_content_approved_action_taken(self):
        # override because Addon's get content reviewed if marked as Approve
        action = DECISION_ACTIONS.AMO_APPROVE
        self.decision.update(action=action)
        assert self.decision.target_versions.exists()
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.process_action()
        assert activity.log == amo.LOG.APPROVE_LISTING_CONTENT
        # no versions in the args though
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}

        counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert (
            counter.content_review_status
            == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
        )
        self.assertCloseToNow(counter.last_content_review)

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def test_reporter_content_approve_report(self):
        subject = self._test_reporter_content_approved_action_taken()
        assert len(mail.outbox) == 2
        self._test_reporter_content_approve_email(subject)

    def test_reporter_appeal_approve(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                addon=self.decision.addon,
                user=self.decision.user,
                rating=self.decision.rating,
                collection=self.decision.collection,
                action=DECISION_ACTIONS.AMO_APPROVE,
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        self.cinder_job.reload()
        subject = self._test_reporter_content_approved_action_taken()
        assert len(mail.outbox) == 1  # only abuse_report_auth reporter
        self._test_reporter_appeal_approve_email(subject)

    def test_content_approve_rejected_listing_content(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED,
        )
        self.addon.update(status=amo.STATUS_REJECTED)
        action = DECISION_ACTIONS.AMO_APPROVE
        self.decision.update(action=action)
        assert self.decision.target_versions.exists()
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.process_action()
        # no versions in the args though
        assert activity.log == amo.LOG.APPROVE_REJECTED_LISTING_CONTENT
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user

        assert (
            self.decision.reload().metadata.get('previous_status')
            == amo.STATUS_REJECTED
        )

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 3
        second_activity, third_activity = ActivityLog.objects.exclude(
            pk=activity.pk
        ).filter()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert third_activity.log == amo.LOG.CHANGE_STATUS

        counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert (
            counter.content_review_status
            == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
        )
        self.assertCloseToNow(counter.last_content_review)

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 3
        self._test_reporter_content_approve_email(subject)
        assert 'within policy, and based on that determination' in mail.outbox[-1].body
        assert 'It is now available' in mail.outbox[-1].body
        assert 'information on its availability.' not in mail.outbox[-1].body

    def test_content_approve_rejected_listing_content_but_awaiting_approval(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED,
        )
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_REJECTED)
        action = DECISION_ACTIONS.AMO_APPROVE
        self.decision.update(action=action)
        assert self.decision.target_versions.exists()
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.process_action()
        # no versions in the args though
        assert activity.log == amo.LOG.APPROVE_REJECTED_LISTING_CONTENT
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user

        assert (
            self.decision.reload().metadata.get('previous_status')
            == amo.STATUS_REJECTED
        )

        assert self.addon.reload().status == amo.STATUS_NOMINATED
        assert ActivityLog.objects.count() == 4
        second_activity, third_activity, fourth_activity = ActivityLog.objects.exclude(
            pk=activity.pk
        ).filter()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The status ends up being set twice
        assert third_activity.log == fourth_activity.log == amo.LOG.CHANGE_STATUS

        counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert (
            counter.content_review_status
            == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
        )
        self.assertCloseToNow(counter.last_content_review)

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 3
        self._test_reporter_content_approve_email(subject)
        assert 'within policy, and based on that determination' in mail.outbox[-1].body
        assert 'It is now available' not in mail.outbox[-1].body
        assert 'information on its availability.' in mail.outbox[-1].body

    def test_email_content_not_escaped(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        super().test_email_content_not_escaped()


# Those tests can call signing when making things public. We want to test that
# it works correctly, so we set ENABLE_ADDON_SIGNING to True and mock the
# actual signing call below in setUp().
@override_settings(ENABLE_ADDON_SIGNING=True)
class TestContentActionApproveVersion(
    PositiveContentActionMixin, BaseContentActionMixin, TestCase
):
    ActionClass = ContentActionApproveVersion
    default_decision_action = DECISION_ACTIONS.AMO_APPROVE_VERSION
    activity_log_action = amo.LOG.APPROVE_VERSION

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.reviewer = user_factory()
        self.addon = addon_factory(users=(self.author,), name='<b>Bad Addön</b>')
        self.old_version = self.addon.current_version
        self.version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        self.another_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        self.addon.reload()
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)
        self.decision.update(addon=self.addon)
        self.decision.target_versions.set((self.version, self.old_version))
        self.past_negative_decision.update(
            addon=self.addon, action=self.default_decision_action
        )
        self.past_negative_decision.target_versions.set(
            (self.version, self.old_version)
        )
        patcher = patch('olympia.abuse.actions.sign_file')
        self.addCleanup(patcher.stop)
        self.sign_file_mock = patcher.start()

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action_helper = ActionClass(self.decision)
        assert action_helper.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def _test_reporter_content_approved_action_taken(self):
        # override because Addon versions can get signed
        self.decision.update(action=self.default_decision_action)
        assert self.decision.target_versions.exists()
        action_helper = self.ActionClass(self.decision)
        # process_action is only available for reviewer tools decisions.
        with self.assertRaises(NotImplementedError):
            action_helper.process_action()

        self.decision.update(reviewer_user=self.reviewer)
        activity = action_helper.process_action()

        assert self.version.file.reload().status == amo.STATUS_APPROVED
        self.assertCloseToNow(self.version.file.approval_date)
        assert self.old_version.file.approval_date is None  # would have been set before
        self.sign_file_mock.assert_called_with(self.version.file)
        self.sign_file_mock.assert_called_once()  # we didn't call it with old_version

        assert activity.log == amo.LOG.APPROVE_VERSION
        # versions in the args
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
        ]
        assert activity.user == self.reviewer
        # exclude this extra activity log - we'll test specificially for it elsewhere
        activity_log_qs = ActivityLog.objects.exclude(action=amo.LOG.UNLISTED_SIGNED.id)
        assert activity_log_qs.count() == 3
        second_activity = (
            activity_log_qs.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.reviewer
        assert second_activity.details == {'comments': self.decision.private_notes}
        third_activity = (
            activity_log_qs.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id)
            .get()
        )
        assert third_activity.log == amo.LOG.CONFIRM_AUTO_APPROVED
        assert third_activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.old_version,
        ]
        assert third_activity.user == self.reviewer

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        assert len(mail.outbox) == 0
        if self.decision.cinder_job:
            self.decision.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def test_reporter_appeal_approve(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                addon=self.decision.addon,
                user=self.decision.user,
                rating=self.decision.rating,
                collection=self.decision.collection,
                action=self.default_decision_action,
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        self.cinder_job.reload()
        subject = self._test_reporter_content_approved_action_taken()
        assert len(mail.outbox) == 2  # one for the author, one for the reporter
        self._test_reporter_appeal_approve_email(subject)

    def test_execute_action(self):
        # testing the case of: listed versions; human review
        for version in (self.version, self.old_version):
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now(),
                pending_rejection_by=self.task_user,
                pending_content_rejection=False,
            )
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_until_next_approval=True,
            auto_approval_disabled_until_next_approval_unlisted=True,
        )
        # test the vanilla case, where there is no cinder_job
        self.decision.update(cinder_job=None)
        self._test_reporter_content_approved_action_taken()

        self.assertCloseToNow(self.version.reload().human_review_date)
        self.assertCloseToNow(self.old_version.reload().human_review_date)
        assert self.version.reviewerflags.reload().pending_rejection is None
        assert self.old_version.reviewerflags.reload().pending_rejection is None
        assert (
            AddonApprovalsCounter.objects.get(addon=self.addon).content_review_status
            == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
        )
        assert self.addon.auto_approval_disabled_until_next_approval is False
        assert self.addon.auto_approval_disabled_until_next_approval_unlisted is True

        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [self.author.email]
        assert 'has been approved' in mail.outbox[0].body

    def test_execute_action_no_files_awaiting_review(self):
        self.version.file.update(status=amo.STATUS_APPROVED)
        self.decision.update(
            cinder_job=None,
            action=self.default_decision_action,
            reviewer_user=self.reviewer,
        )
        assert self.decision.target_versions.exists()
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=151
        )
        # no autoapproval summary for old_version
        action_helper = self.ActionClass(self.decision)

        activity = action_helper.process_action()
        assert activity.log == amo.LOG.CONFIRM_AUTO_APPROVED
        # versions in the args
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
        ]
        assert activity.user == self.reviewer

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.reviewer
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert self.version.autoapprovalsummary.reload().confirmed is True
        assert hasattr(self.old_version, 'autoapprovalsummary') is False

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        action_helper.notify_owners()
        assert len(mail.outbox) == 0

    def test_execute_action_unlisted(self):
        # testing the case of: unlisted versions; human review
        self.make_addon_unlisted(self.addon)
        assert self.addon.status == amo.STATUS_NULL
        ActivityLog.objects.all().delete()
        for version in (self.version, self.old_version):
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now(),
                pending_rejection_by=self.task_user,
                pending_content_rejection=False,
            )
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_until_next_approval=True,
            auto_approval_disabled_until_next_approval_unlisted=True,
        )
        # test the vanilla case, where there is no cinder_job
        self.decision.update(cinder_job=None)
        self._test_reporter_content_approved_action_taken()

        self.assertCloseToNow(self.version.reload().human_review_date)
        self.assertCloseToNow(self.old_version.reload().human_review_date)
        assert self.version.reviewerflags.reload().pending_rejection is None
        assert self.old_version.reviewerflags.reload().pending_rejection is None
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()
        assert self.addon.reload().auto_approval_disabled_until_next_approval is True
        assert self.addon.auto_approval_disabled_until_next_approval_unlisted is False
        assert ActivityLog.objects.get(action=amo.LOG.UNLISTED_SIGNED.id).arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version.file,
        ]

        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [self.author.email]
        assert 'has been approved' in mail.outbox[0].body

    def test_execute_action_promoted(self):
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert not self.addon.promoted_groups()
        self.test_execute_action()
        assert self.addon.promoted_groups()
        assert self.version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert self.old_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()

    def test_execute_action_not_human(self):
        # testing the case of: listed versions; not human
        self.reviewer = self.task_user
        for version in (self.version, self.old_version):
            VersionReviewerFlags.objects.create(
                version=version,
                pending_rejection=datetime.now(),
                pending_rejection_by=self.task_user,
                pending_content_rejection=False,
            )
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled_until_next_approval=True,
            auto_approval_disabled_until_next_approval_unlisted=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.UNREVIEWED,
            counter=1,
        )
        # test the vanilla case, where there is no cinder_job
        self.decision.update(cinder_job=None)
        self._test_reporter_content_approved_action_taken()

        assert self.version.reload().human_review_date is None
        assert self.old_version.reload().human_review_date is None
        self.assertCloseToNow(self.version.reviewerflags.reload().pending_rejection)
        self.assertCloseToNow(self.old_version.reviewerflags.reload().pending_rejection)
        aacounter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert (
            aacounter.content_review_status
            == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.UNREVIEWED
        )
        assert aacounter.counter == 0
        assert self.addon.auto_approval_disabled_until_next_approval is True
        assert self.addon.auto_approval_disabled_until_next_approval_unlisted is True

        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [self.author.email]
        assert 'has been approved' in mail.outbox[0].body

    def test_email_content_not_escaped(self):
        ActivityLog.objects.create(
            amo.LOG.APPROVE_VERSION,
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
            user=self.reviewer,
        )
        super().test_email_content_not_escaped()


class TestContentActionRejectListingContent(TestContentActionDisableAddon):
    ActionClass = ContentActionRejectListingContent
    default_decision_action = DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT
    disable_snippet = 'until you address the violations and request a further review'
    activity_log_action = amo.LOG.REJECT_LISTING_CONTENT

    def _process_action_and_notify(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        activity = action_helper.process_action()
        assert activity
        assert activity.log == self.activity_log_action
        assert self.addon.reload().status == amo.STATUS_REJECTED
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() >= 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).first()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == 0

        # get this again, to replicate how send_notifications works
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()

    def _test_approve_appeal_or_override(self, ActionClass):
        self.addon.update(status=amo.STATUS_REJECTED)
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert activity.log == amo.LOG.APPROVE_REJECTED_LISTING_CONTENT
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 3
        # We have an additional activity if the add-on status wasn't STATUS_NOMINATED
        second_activity = (
            ActivityLog.objects.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CHANGE_STATUS.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_execute_action(self):
        self._process_action_and_notify()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)
        # Content-rejection doesn't affect auto-approval disabled flags.
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()

    def test_hold_action(self):
        self.decision.update(action=self.default_decision_action)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_REJECT_LISTING_CONTENT
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
        ]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert activity.details == {
            'comments': self.decision.reasoning,
            'human_review': False,
            'policy_texts': [self.policy.full_text()],
        }
        # Content-rejection doesn't affect auto-approval disabled flags.
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()

    def test_addon_version_has_target_versions(self):
        # This type of action doesn't have any target_versions, so addon_version will
        # just be the current version.
        assert (
            self.ActionClass(self.decision).addon_version == self.addon.current_version
        )

        # Also check that if the decision does have target_versions, the action class
        # ignores them
        assert self.decision.target_versions.exists()
        assert not self.ActionClass(self.decision).target_versions.exists()

    def test_log_action_args(self):
        activity = self.ActionClass(self.decision).log_action(self.activity_log_action)
        assert self.addon in activity.arguments
        assert activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
        ]
        assert activity.details == {
            'human_review': False,
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }

    def test_approve_appeal_success_but_listing_rejected(self):
        # This test doesn't apply for this ActionClass.
        pass

    def test_approve_override_success_but_listing_rejected(self):
        pass
        # This test doesn't apply for this ActionClass.

    def _test_approve_appeal_or_override_but_not_approved(self, ActionClass):
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_REJECTED)

        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.addon.reload().status == amo.STATUS_NOMINATED
        assert activity.log == amo.LOG.APPROVE_REJECTED_LISTING_CONTENT
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 3
        second_activity = (
            ActivityLog.objects.exclude(pk=activity.pk)
            .exclude(action=amo.LOG.CHANGE_STATUS.id)
            .get()
        )
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.addon, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: {self.addon.name}',
                fragment='information on its availability',
            )

    def test_already_taken_down(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        # it should work the same if it's already rejected - the developer can ask for
        # a new review, and we reject it again
        self._process_action_and_notify()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body

    def test_target_appeal_decline(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED,
        )
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        ActivityLog.objects.all().delete()
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_REJECTED
        assert self.addon.addonapprovalscounter.reload().content_review_status == (
            AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL
        )
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_should_be_skipped_by_automation(self):
        assert not self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )

        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert self.ActionClass.should_be_skipped_by_automation(
            addon=self.addon, version=self.version
        )


class TestContentActionCollection(
    PositiveContentActionMixin,
    NegativeContentActionMixin,
    BaseContentActionMixin,
    TestCase,
):
    ActionClass = ContentActionDeleteCollection
    default_decision_action = DECISION_ACTIONS.AMO_DELETE_COLLECTION

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
        self.past_negative_decision.update(
            addon=None,
            collection=self.collection,
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
        )

    def _test_delete_collection(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        log_entry = action_helper.process_action()

        assert self.collection.reload()
        assert self.collection.deleted
        assert self.collection.slug
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_DELETED.id)
        assert activity == log_entry
        assert activity.arguments == [self.collection, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.collection, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        subject = f'Mozilla Add-ons: {self.collection.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(
            private_notes='', action=DECISION_ACTIONS.AMO_DELETE_COLLECTION
        )
        action_helper = self.ActionClass(self.decision)
        action_helper.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_deleted(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        self.collection.delete()
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_delete_collection(self):
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_delete_collection_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                collection=self.collection, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action_helper = ActionClass(self.decision)
        assert action_helper.process_action() is None

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: {self.collection.name}'

    def _test_approve_appeal_or_override(self, ActionClass):
        self.collection.update(deleted=True)
        log_entry, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert self.collection.reload()
        assert not self.collection.deleted
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_UNDELETED.id)
        assert activity == log_entry
        assert activity.arguments == [self.collection, self.decision, self.policy]
        assert activity.user == self.task_user
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.collection, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_target_appeal_decline(self):
        self.collection.update(deleted=True)
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.collection.reload()
        assert self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        self.collection.update(author=self.task_user)
        assert action_helper.should_hold_action() is True

        self.collection.deleted = True
        assert action_helper.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_COLLECTION_DELETED
        assert activity.arguments == [self.collection, self.decision, self.policy]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.collection, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}


class TestContentActionRating(
    PositiveContentActionMixin,
    NegativeContentActionMixin,
    BaseContentActionMixin,
    TestCase,
):
    ActionClass = ContentActionDeleteRating
    default_decision_action = DECISION_ACTIONS.AMO_DELETE_RATING

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.rating = Rating.objects.create(
            addon=addon_factory(), user=self.author, body='Saying something <b>bad</b>'
        )
        self.cinder_job.abusereport_set.update(rating=self.rating, guid=None)
        self.decision.update(addon=None, rating=self.rating)
        self.past_negative_decision.update(
            addon=None, rating=self.rating, action=DECISION_ACTIONS.AMO_DELETE_RATING
        )
        ActivityLog.objects.all().delete()

    def _test_delete_rating(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.action == self.default_decision_action
        activity = action_helper.process_action()
        assert activity.log == amo.LOG.DELETE_RATING
        assert activity.arguments == [
            self.rating,
            self.decision,
            self.policy,
            self.rating.addon,
        ]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'addon_id': self.rating.addon_id,
            'addon_title': str(self.rating.addon.name),
            'body': self.rating.body,
            'is_flagged': False,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.rating, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}

        assert self.rating.reload().deleted
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        subject = f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(
            private_notes='', action=DECISION_ACTIONS.AMO_DELETE_RATING
        )
        action_helper = self.ActionClass(self.decision)
        action_helper.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_deleted(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action_helper = self.ActionClass(self.decision)
        assert action_helper.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_delete_rating(self):
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_delete_rating_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                rating=self.rating, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.final_decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.final_decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action_helper = ActionClass(self.decision)
        assert action_helper.process_action() is None

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        return f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'

    def _test_approve_appeal_or_override(self, ActionClass):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        activity, action_helper = self._reverse_appeal_or_override(ActionClass)

        assert activity.log == amo.LOG.UNDELETE_RATING
        assert activity.arguments == [
            self.rating,
            self.decision,
            self.policy,
            self.rating.addon,
        ]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'addon_id': self.rating.addon_id,
            'addon_title': str(self.rating.addon.name),
            'body': self.rating.body,
            'is_flagged': False,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.rating, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}

        assert not self.rating.reload().deleted
        # The reversal itself never notifies anyone.
        assert len(mail.outbox) == 0

        if not self.decision.override_of_id:
            self.cinder_job.notify_reporters(action_helper)
            action_helper.notify_owners()
            self._test_owner_restore_email(
                f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
            )

    def test_target_appeal_decline(self):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action_helper = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action_helper.process_action() is None

        self.rating.reload()
        assert self.rating.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action_helper)
        action_helper.notify_owners()
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action_helper = self.ActionClass(self.decision)
        assert action_helper.should_hold_action() is False

        AddonUser.objects.create(addon=self.rating.addon, user=self.rating.user)
        assert action_helper.should_hold_action() is False
        self.make_addon_promoted(self.rating.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action_helper.should_hold_action() is False
        self.rating.update(
            reply_to=Rating.objects.create(
                addon=self.rating.addon, user=user_factory(), body='original'
            )
        )
        assert action_helper.should_hold_action() is True

        self.rating.update(deleted=self.rating.id)
        assert action_helper.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        action_helper = self.ActionClass(self.decision)
        activity = action_helper.hold_action()
        assert activity.log == amo.LOG.HELD_ACTION_DELETE_RATING
        assert activity.arguments == [
            self.rating,
            self.decision,
            self.policy,
            self.rating.addon,
        ]
        assert activity.user == self.task_user
        assert activity.details == {
            'comments': self.decision.reasoning,
            'policy_texts': [self.policy.full_text()],
        }
        assert ActivityLog.objects.count() == 2
        second_activity = ActivityLog.objects.exclude(pk=activity.pk).get()
        assert second_activity.log == amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert second_activity.arguments == [self.rating, self.decision]
        assert second_activity.user == self.task_user
        assert second_activity.details == {'comments': self.decision.private_notes}


class TestContentActionLegalTakedownDisableAddon(TestContentActionDisableAddon):
    ActionClass = ContentActionLegalTakedownDisableAddon
    default_decision_action = DECISION_ACTIONS.AMO_LEGAL_DISABLE_ADDON

    def test_execute_action(self):
        self._process_action_and_notify()
        assert len(mail.outbox) == 0
        flags = self.addon.reviewerflags.reload()
        assert flags.auto_approval_disabled
        assert flags.auto_approval_disabled_unlisted

    def test_approve_appeal_success(self):
        # No appeals
        pass

    def test_approve_appeal_success_but_listing_rejected(self):
        # No appeals
        pass

    def test_approve_appeal_success_but_not_approved(self):
        # No appeals
        pass

    def test_email_content_not_escaped(self):
        # No emails
        pass

    def test_execute_action_after_reporter_appeal(self):
        # Not a supported action to use as an override to support a reporter appeal
        pass

    def test_notify_owners_non_public_url(self):
        # No emails
        pass

    def test_notify_owners_with_for_proactive_decision(self):
        # No emails
        pass

    def test_notify_owners_with_for_third_party_decision(self):
        # No emails
        pass

    def test_notify_owners_with_manual_reasoning_text(self):
        # No emails
        pass

    def test_notify_reporters_reporters_provided(self):
        # No emails
        pass


def test_no_action_duplicates():
    """ContentAction classes action attribute must be unique, no two classes
    can define the same, because it's used to build the
    CONTENT_ACTION_FROM_DECISION_ACTION dict."""
    actions_from_content_action_classes = sorted(
        [
            v.action
            for v in vars(olympia.abuse.actions).values()
            if isclass(v) and issubclass(v, ContentAction) and v.action
        ]
    )
    assert len(actions_from_content_action_classes) == len(
        set(actions_from_content_action_classes)
    )

    # There should be at least as many DECISION_ACTIONS as there are classes,
    # except for AMO_ESCALATE_ADDON (which is obsolete) and AMO_REQUEUE (which
    # is not a real action, it's an internal re-queuing)
    available_decision_actions = sorted(
        [
            action
            for action in DECISION_ACTIONS
            if action
            not in (DECISION_ACTIONS.AMO_REQUEUE, DECISION_ACTIONS.AMO_ESCALATE_ADDON)
        ]
    )
    assert actions_from_content_action_classes == available_decision_actions
