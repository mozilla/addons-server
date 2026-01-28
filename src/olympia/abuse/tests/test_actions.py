import json
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.files.base import ContentFile
from django.urls import reverse

import responses
from waffle.testutils import override_switch

from olympia import amo
from olympia.access.models import Group
from olympia.activity.models import (
    ActivityLog,
    ActivityLogToken,
    AttachmentLog,
    ReviewActionReasonLog,
)
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonUser
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.models import Block, BlockVersion
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.permissions import ADDONS_HIGH_IMPACT_APPROVE
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.core import set_user
from olympia.files.models import File
from olympia.promoted.models import PromotedGroup
from olympia.ratings.models import Rating
from olympia.reviewers.models import ReviewActionReason
from olympia.versions.models import VersionReviewerFlags

from ..actions import (
    ContentAction,
    ContentActionApproveInitialDecision,
    ContentActionApproveListingContent,
    ContentActionBanUser,
    ContentActionBlockAddon,
    ContentActionDeleteCollection,
    ContentActionDeleteRating,
    ContentActionDisableAddon,
    ContentActionForwardToLegal,
    ContentActionIgnore,
    ContentActionOverrideApprove,
    ContentActionRejectListingContent,
    ContentActionRejectVersion,
    ContentActionRejectVersionDelayed,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from ..models import AbuseReport, CinderAppeal, CinderJob, CinderPolicy, ContentDecision


class BaseTestContentAction:
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
            action=DECISION_ACTIONS.AMO_APPROVE,
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

    def _test_owner_restore_email(self, subject):
        mail_item = mail.outbox[0]
        assert len(mail.outbox) == 1
        self._check_owner_email(mail_item, subject, 'we have restored')
        assert 'right to appeal' not in mail_item.body
        assert '&#x27;' not in mail_item.body
        assert self.decision.reasoning in mail_item.body
        assert self.decision.private_notes not in mail_item.body

    def _test_approve_appeal_or_override(ContentActionClass):
        # Common things that we expect to happen after a successful appeal or
        # override of a negative action.
        raise NotImplementedError

    def test_approve_appeal_success(self):
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)
        assert 'After reviewing your appeal' in mail.outbox[0].body

    def test_approve_override_success(self):
        self.decision.update(override_of=self.past_negative_decision)
        self._test_approve_appeal_or_override(ContentActionOverrideApprove)
        assert 'After reviewing your appeal' not in mail.outbox[0].body

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        raise NotImplementedError

    def _test_reporter_content_approved_action_taken(self):
        # For most ActionClasses, there is no action taken.
        return self._test_reporter_no_action_taken(
            ActionClass=ContentActionApproveListingContent,
            action=DECISION_ACTIONS.AMO_APPROVE,
        )

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
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        self.cinder_job.reload()
        subject = self._test_reporter_content_approved_action_taken()
        assert len(mail.outbox) == 1  # only abuse_report_auth reporter
        self._test_reporter_appeal_approve_email(subject)

    def test_owner_content_approve_report_email(self):
        # This isn't called by cinder actions, but is triggered by reviewer actions
        subject = self._test_reporter_no_action_taken(
            ActionClass=ContentActionApproveInitialDecision,
            action=DECISION_ACTIONS.AMO_APPROVE,
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

    def test_email_content_not_escaped(self):
        unsafe_str = '<script>jar=window.triggerExploit();"</script>'
        self.decision.update(reasoning=unsafe_str)
        action = self.ActionClass(self.decision)
        action.notify_owners()
        assert unsafe_str in mail.outbox[0].body

        action = ContentActionApproveListingContent(self.decision)
        mail.outbox.clear()
        action.notify_reporters(
            reporter_abuse_reports=[self.abuse_report_auth], is_appeal=True
        )
        assert unsafe_str in mail.outbox[0].body

    def test_log_action_user(self):
        # just an arbitrary activity class
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        assert (
            self.ActionClass(self.decision).log_action(amo.LOG.ADMIN_USER_UNBAN).user
            == reviewer
        )

    def test_log_action_saves_policy_texts(self):
        # update the policy with a placeholder - these are't supposed to be used with
        # Cinder originated policy decisions, but testing the edge case.
        self.policy.update(text='This is {JUDGEMENT} thing')
        assert self.ActionClass(self.decision).log_action(
            amo.LOG.ADMIN_USER_UNBAN
        ).details['policy_texts'] == [
            'Parent Policy, specifically Bad policy: This is {JUDGEMENT} thing'
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


class TestContentActionUser(BaseTestContentAction, TestCase):
    ActionClass = ContentActionBanUser

    def setUp(self):
        super().setUp()
        self.user = user_factory(display_name='<b>Bad Hørse</b>')
        self.cinder_job.abusereport_set.update(user=self.user, guid=None)
        self.decision.update(addon=None, user=self.user)
        self.past_negative_decision.update(
            addon=None, user=self.user, action=DECISION_ACTIONS.AMO_BAN_USER
        )

    def _test_ban_user(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        activity = action.process_action()
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.user.name}'
        self._test_owner_takedown_email(subject, 'has been suspended')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(private_notes='', action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        action.process_action()
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
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_ban_user_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
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

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        self.user.reload()
        assert not self.user.banned
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        return f'Mozilla Add-ons: {self.user.name}'

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.decision.update(action=DECISION_ACTIONS.AMO_APPROVE)
        self.user.update(banned=self.days_ago(1), deleted=True)
        action = ContentActionClass(self.decision)
        activity = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.user.name}')

    def test_target_appeal_decline(self):
        self.user.update(banned=self.days_ago(1), deleted=True)
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
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
        self.make_addon_promoted(addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action.should_hold_action() is True

        self.user.banned = datetime.now()
        assert action.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
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
class TestContentActionDisableAddon(BaseTestContentAction, TestCase):
    ActionClass = ContentActionDisableAddon
    activity_log_action = amo.LOG.FORCE_DISABLE
    disable_snippet = 'permanently disabled'
    takedown_decision_action = DECISION_ACTIONS.AMO_DISABLE_ADDON

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
            addon=self.addon, action=self.takedown_decision_action
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
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        activity = action.process_action()
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(private_notes='', action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        action.process_action()
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_disabled(self):
        self.decision.update(action=self.takedown_decision_action)
        self.addon.update(status=amo.STATUS_DISABLED)
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_execute_action(self):
        subject = self._process_action_and_notify()
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_execute_action_after_reporter_appeal(self):
        original_job = CinderJob.objects.create(
            job_id='original',
            decision=ContentDecision.objects.create(
                addon=self.addon, action=DECISION_ACTIONS.AMO_APPROVE
            ),
        )
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._process_action_and_notify()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = ContentActionClass(self.decision)
        activity = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def _test_reporter_content_approved_action_taken(self):
        # override because Addon's get content reviewed if marked as Approve
        action = DECISION_ACTIONS.AMO_APPROVE
        self.decision.update(action=action)
        action = ContentActionApproveListingContent(self.decision)
        activity = action.process_action()
        assert activity.log == amo.LOG.APPROVE_LISTING_CONTENT
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
        assert counter.last_content_review_pass is True
        self.assertCloseToNow(counter.last_content_review)

        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        return f'Mozilla Add-ons: {self.addon.name}'

    def test_content_approve_rejected_listing_content(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.addon.update(status=amo.STATUS_REJECTED)
        action = DECISION_ACTIONS.AMO_APPROVE
        self.decision.update(action=action)
        action = ContentActionApproveListingContent(self.decision)
        activity = action.process_action()
        assert activity.log == amo.LOG.APPROVE_LISTING_CONTENT
        assert activity.arguments == [self.addon, self.decision, self.policy]
        assert activity.user == self.task_user

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
        assert counter.last_content_review_pass is True
        self.assertCloseToNow(counter.last_content_review)

        assert len(mail.outbox) == 0
        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'

        assert len(mail.outbox) == 3
        self._test_reporter_content_approve_email(subject)
        assert 'within policy, and based on that determination' in mail.outbox[-1].body

    def test_target_appeal_decline(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
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
        self.decision.update(reasoning='')
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self.decision.update(reasoning='')
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_notify_owners_with_manual_reasoning_text(self):
        self.decision.update(
            action=self.takedown_decision_action,
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
        self.decision.update(action=self.takedown_decision_action)
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
        self.decision.update(action=self.takedown_decision_action)
        self.ActionClass(self.decision).notify_owners()
        mail_item = mail.outbox[0]
        self._check_owner_email(
            mail_item, f'Mozilla Add-ons: {self.addon.name}', self.disable_snippet
        )
        assert 'right to appeal' in mail_item.body
        assert 'in an assessment performed on our own initiative' in mail_item.body
        assert 'based on a report we received from a third party' not in mail_item.body

    def test_notify_owners_non_public_url(self):
        self.decision.update(action=self.takedown_decision_action)
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
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action.should_hold_action() is True

        self.addon.status = amo.STATUS_DISABLED
        assert action.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
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
        activity = action.hold_action()
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

    def test_forward_from_reviewers_no_job(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_LEGAL_FORWARD, cinder_job=None)
        action = ContentActionForwardToLegal(self.decision)
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        action.process_action()

        assert CinderJob.objects.get(job_id='1234-xyz')
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body['reasoning'] == self.decision.reasoning
        assert request_body['queue_slug'] == 'legal-escalations'

    def test_forward_from_reviewers_with_job(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_LEGAL_FORWARD)
        action = ContentActionForwardToLegal(self.decision)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{self.cinder_job.job_id}/decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )

        action.process_action()

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

        # add a ReviewActionReason from a previous decision via the reviewer tools
        reason = ReviewActionReason.objects.create(
            name='reason 2',
            is_active=True,
            cinder_policy=self.policy,
            canned_response='.',
        )
        ReviewActionReasonLog.objects.create(reason=reason, activity_log=activity)
        new_activity = self.ActionClass(self.decision).log_action(
            self.activity_log_action
        )
        assert new_activity.arguments == [
            self.addon,
            self.decision,
            self.policy,
            self.version,
            self.old_version,
            reason,
        ]

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

    def _test_approve_appeal_or_override_but_listing_rejected(self, ContentActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = ContentActionClass(self.decision)
        activity = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_approve_appeal_success_but_listing_rejected(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override_but_listing_rejected(
            ContentActionTargetAppealApprove
        )
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body
        assert self.addon.reload().status == amo.STATUS_REJECTED

    def test_approve_override_success_but_listing_rejected(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.decision.update(override_of=self.past_negative_decision)
        self._test_approve_appeal_or_override_but_listing_rejected(
            ContentActionOverrideApprove
        )
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body
        assert self.addon.reload().status == amo.STATUS_REJECTED


class TestContentActionRejectVersion(TestContentActionDisableAddon):
    ActionClass = ContentActionRejectVersion
    activity_log_action = amo.LOG.REJECT_VERSION
    disable_snippet = 'versions of your Extension have been disabled'
    takedown_decision_action = DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON

    def setUp(self):
        super().setUp()
        # Set up another_version as approved so that the rejection of the other
        # 2 versions leaves one version approved and the add-on stays public.
        self.another_version.file.update(status=amo.STATUS_APPROVED)

    def _test_reject_version(self, *, content_review, expected_emails_from_action=0):
        old_version_original_status = self.old_version.file.status
        version_original_status = self.version.file.status
        self.decision.update(
            action=self.takedown_decision_action,
            metadata={'content_review': content_review},
        )
        action = ContentActionRejectVersion(self.decision)
        # process_action is only available for reviewer tools decisions.
        with self.assertRaises(NotImplementedError):
            action.process_action()

        # but with a reviewer attached to the decision we can proceed
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        activity = action.process_action()
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

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.old_version.file.update(
            status=amo.STATUS_DISABLED, original_status=amo.STATUS_APPROVED
        )
        # set-up where version.file doesn't have an original_status for some reason
        self.version.file.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = ContentActionClass(self.decision)
        activity = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_approve_appeal_success_but_listing_rejected(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.past_negative_decision.update(appeal_job=self.cinder_job)
        self._test_approve_appeal_or_override(ContentActionTargetAppealApprove)
        assert self.addon.reload().status == amo.STATUS_REJECTED
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body

    def test_approve_override_success_but_listing_rejected(self):
        self.addon.update(status=amo.STATUS_REJECTED)
        AddonApprovalsCounter.objects.create(
            addon=self.addon, last_content_review_pass=False
        )
        self.decision.update(override_of=self.past_negative_decision)
        self._test_approve_appeal_or_override(ContentActionOverrideApprove)
        assert self.addon.reload().status == amo.STATUS_REJECTED
        assert 'listing on Mozilla Add-ons remains unavailable' in mail.outbox[0].body

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
        self.decision.update(override_of=self.past_negative_decision)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.old_version.file.update(status=amo.STATUS_APPROVED)
        ActivityLog.objects.all().delete()
        action = ContentActionOverrideApprove(self.decision)
        activity = action.process_action()

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
            action=self.takedown_decision_action,
            reviewer_user=user_factory(),
        )
        action = self.ActionClass(self.decision)
        action.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_disabled(self):
        self.decision.update(
            action=self.takedown_decision_action, reviewer_user=user_factory()
        )
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.old_version.file.update(status=amo.STATUS_DISABLED)
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_already_disabled_delayed_rejection(self):
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
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
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
        action = ContentActionRejectVersionDelayed(self.decision)
        assert action.process_action() is None
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

    def test_already_disabled_by_developer(self):
        # If versions were disabled by the developer, that doesn't prevent the
        # rejection from being applied and recorded.
        self.version.is_user_disabled = True
        self.old_version.is_user_disabled = True
        ActivityLog.objects.all().delete()
        subject = self._test_reject_version(content_review=False)
        assert len(mail.outbox) == 3
        self._test_reporter_takedown_email(subject)

    def test_already_disabled_by_developer_delayed_rejection(self):
        # If versions were disabled by the developer, that doesn't prevent the
        # delayed rejection from being applied and recorded.
        self.version.is_user_disabled = True
        self.old_version.is_user_disabled = True
        ActivityLog.objects.all().delete()
        self.test_execute_action_delayed()

    def test_execute_action(self):
        subject = self._test_reject_version(content_review=False)
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
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_reject_version(content_review=False)
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reject_version_delayed(
        self, *, content_review, expected_emails_from_action=0
    ):
        original_statuses = {
            version.file.pk: version.file.status
            for version in (self.old_version, self.version)
        }
        in_the_future = datetime.now() + timedelta(days=14, hours=1)
        self.decision.update(
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON,
            metadata={
                'delayed_rejection_date': in_the_future.isoformat(),
                'content_review': content_review,
            },
        )
        action = ContentActionRejectVersionDelayed(self.decision)
        # process_action is only available for reviewer tools decisions.
        with self.assertRaises(NotImplementedError):
            action.process_action()

        # but with a reviewer attached to the decision we can proceed
        reviewer = user_factory()
        self.decision.update(reviewer_user=reviewer)
        activity = action.process_action()
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

    def test_execute_action_delayed(self, *, content_review=False):
        subject = self._test_reject_version_delayed(content_review=content_review)
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
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
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
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
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

        user = user_factory()
        self.decision.update(reviewer_user=user)
        activity = action.hold_action()
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

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        self.version.file.update(is_signed=True)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self.decision.target_versions.add(self.another_version)
        assert self.decision.target_versions.filter(file__is_signed=True).exists()
        assert action.should_hold_action() is True

        self.version.file.update(is_signed=False)
        self.decision = ContentDecision.objects.get(id=self.decision.id)
        assert not self.decision.target_versions.filter(file__is_signed=True).exists()
        assert action.should_hold_action() is False

    def test_should_hold_action_some_versions_remain(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON)
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self.version.file.update(is_signed=True)

        # While there are more public listed versions that wouldn't be affected
        # the rejection can go through without being held.
        action = self.ActionClass(self.decision)
        assert action.remaining_public_listed_versions().exists()
        assert action.should_hold_action() is False

        # If that last remaining version is unlisted, suddenly we do hold the
        # rejection - no public listed versions would remain if that went
        # through.
        self.another_version.update(channel=amo.CHANNEL_UNLISTED)
        assert not action.remaining_public_listed_versions().exists()
        assert action.should_hold_action() is True

        # If that last remaining version is listed but not public, then we have
        # to hold the rejection once more, since no public listed versions
        # would remain once again.
        self.another_version.update(channel=amo.CHANNEL_LISTED)
        self.another_version.file.update(status=amo.STATUS_DISABLED)
        assert not action.remaining_public_listed_versions().exists()
        assert action.should_hold_action() is True

        # If that version is public but pending rejection we still have to hold
        # the rejection.
        self.another_version.file.update(status=amo.STATUS_APPROVED)
        VersionReviewerFlags.objects.create(
            version=self.another_version,
            pending_rejection=datetime.now(),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        assert action.remaining_public_listed_versions().exists()
        assert action.should_hold_action() is True

    def test_target_appeal_decline(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.version.file.reload()
        assert self.version.file.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners(extra_context={'is_addon_enabled': True})
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: {self.addon.name}', should_allow_uploads=True
        )

    def test_notify_stakeholders(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action = self.ActionClass(self.decision)
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
        action.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 0

        # make the addon promoted
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        action.notify_stakeholders('teh reason')
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
        action.notify_stakeholders('teh reason')
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
        action.notify_stakeholders('teh reason')
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
        action.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 4  # another email
        body = mail.outbox[3].body
        assert 'will be the current' not in body
        assert 'no longer' not in body

        # And check that if no versions were signed we don't send an email
        listed_version.file.update(is_signed=False)
        unlisted_version.file.update(is_signed=False)
        action.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 4

    def test_notify_stakeholders_with_private_notes(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action = self.ActionClass(self.decision)
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
        action.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'teh reason issued for {self.addon.name}'
        assert 'Private notes:' in mail.outbox[0].body
        assert 'These are the private notes.' in mail.outbox[0].body

    def test_notify_stakeholders_with_policy_texts(self):
        stakeholder = user_factory()
        self.decision.target_versions.set([self.version])
        action = self.ActionClass(self.decision)
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
        action.notify_stakeholders('teh reason')
        assert len(mail.outbox) == 1
        assert mail.outbox[0].recipients() == [stakeholder.email]
        assert mail.outbox[0].subject == f'teh reason issued for {self.addon.name}'
        assert 'Policies:' in mail.outbox[0].body
        assert (
            'Parent Policy, specifically Bad policy: Some reason why we can`t do that.'
            in mail.outbox[0].body
        )


class TestContentActionBlockAddon(TestContentActionDisableAddon):
    ActionClass = ContentActionBlockAddon
    takedown_decision_action = DECISION_ACTIONS.AMO_BLOCK_ADDON

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
        subject = super()._process_action_and_notify()

        assert ActivityLog.objects.count() == 4
        block_activity = ActivityLog.objects.all()[3]
        block_version_activity = ActivityLog.objects.all()[2]
        self._check_block_activity_logs(block_activity, block_version_activity)
        assert self.version.blockversion
        assert self.old_version.blockversion

        return subject

    def test_already_disabled(self):
        """For a block action, this shouldn't affect the block, only the disable"""
        self.decision.update(action=self.takedown_decision_action)
        self.addon.update(status=amo.STATUS_DISABLED)
        File.objects.filter(version__addon=self.addon).update(
            status=amo.STATUS_DISABLED
        )
        action = self.ActionClass(self.decision)
        assert action.process_action() is None  # we don't have a disable activity
        assert ActivityLog.objects.count() == 2
        block_activity = ActivityLog.objects.all()[1]
        block_version_activity = ActivityLog.objects.all()[0]
        self._check_block_activity_logs(block_activity, block_version_activity)
        assert self.version.blockversion
        assert self.old_version.blockversion

    def test_already_blocked(self):
        self.decision.update(action=self.takedown_decision_action)
        BlockVersion.objects.create(block=self.addon.block, version=self.version)
        BlockVersion.objects.create(block=self.addon.block, version=self.old_version)
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
        assert ActivityLog.objects.count() == 0

    def test_should_hold_action(self):
        PromotedGroup.objects.get_or_create(
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED, high_profile=True
        )
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert action.should_hold_action() is True

        # if one version is not blocked we still hold the action
        BlockVersion.objects.create(block=self.addon.block, version=self.version)
        assert action.should_hold_action() is True

        BlockVersion.objects.create(block=self.addon.block, version=self.old_version)
        assert action.should_hold_action() is False

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


class TestContentActionRejectListingContent(TestContentActionDisableAddon):
    ActionClass = ContentActionRejectListingContent
    takedown_decision_action = DECISION_ACTIONS.AMO_REJECT_LISTING_CONTENT
    disable_snippet = 'until you address the violations and request a further review'
    activity_log_action = amo.LOG.REJECT_LISTING_CONTENT

    def setUp(self):
        super().setUp()
        # content rejections are not specific to a version
        self.decision.target_versions.clear()

    def _process_action_and_notify(self):
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        activity = action.process_action()
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, self.disable_snippet)
        assert f'Your Extension {self.addon.name}' in mail.outbox[-1].body
        return subject

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.addon.update(status=amo.STATUS_REJECTED)
        ActivityLog.objects.all().delete()
        action = ContentActionClass(self.decision)
        activity = action.process_action()

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert activity.log == amo.LOG.APPROVE_LISTING_CONTENT
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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_hold_action(self):
        self.decision.update(action=self.takedown_decision_action)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
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

    def test_addon_version_has_target_versions(self):
        # This type of action doesn't have any target_versions, so addon_version will
        # just be the current version.
        assert (
            self.ActionClass(self.decision).addon_version == self.addon.current_version
        )

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


class TestContentActionCollection(BaseTestContentAction, TestCase):
    ActionClass = ContentActionDeleteCollection

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
        action = self.ActionClass(self.decision)
        log_entry = action.process_action()

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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: {self.collection.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(
            private_notes='', action=DECISION_ACTIONS.AMO_DELETE_COLLECTION
        )
        action = self.ActionClass(self.decision)
        action.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_deleted(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        self.collection.delete()
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
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
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_collection()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
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

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.collection.update(deleted=True)
        action = ContentActionClass(self.decision)
        log_entry = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_target_appeal_decline(self):
        self.collection.update(deleted=True)
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
        assert action.process_action() is None

        self.collection.reload()
        assert self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_should_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action = self.ActionClass(self.decision)
        assert action.should_hold_action() is False

        self.collection.update(author=self.task_user)
        assert action.should_hold_action() is True

        self.collection.deleted = True
        assert action.should_hold_action() is False

    def test_hold_action(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_COLLECTION)
        action = self.ActionClass(self.decision)
        activity = action.hold_action()
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


class TestContentActionRating(BaseTestContentAction, TestCase):
    ActionClass = ContentActionDeleteRating

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
        action = self.ActionClass(self.decision)
        activity = action.process_action()
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

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        subject = f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        return subject

    def test_log_action_no_notes(self):
        self.decision.update(
            private_notes='', action=DECISION_ACTIONS.AMO_DELETE_RATING
        )
        action = self.ActionClass(self.decision)
        action.process_action()
        assert ActivityLog.objects.count() == 1
        assert not ActivityLog.objects.filter(
            action=amo.LOG.REVIEWER_PRIVATE_COMMENT.id
        ).exists()

    def test_already_deleted(self):
        self.decision.update(action=DECISION_ACTIONS.AMO_DELETE_RATING)
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = self.ActionClass(self.decision)
        assert action.process_action() is None
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
        self.cinder_job.appealed_decisions.add(original_job.decision)
        self.abuse_report_no_auth.update(cinder_job=original_job)
        self.abuse_report_auth.update(cinder_job=original_job)
        CinderAppeal.objects.create(
            decision=original_job.decision, reporter_report=self.abuse_report_auth
        )
        subject = self._test_delete_rating()
        assert len(mail.outbox) == 2
        self._test_reporter_appeal_takedown_email(subject)

    def _test_reporter_no_action_taken(self, *, ActionClass, action):
        self.decision.update(action=action)
        action = ActionClass(self.decision)
        assert action.process_action() is None

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        return f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'

    def _test_approve_appeal_or_override(self, ContentActionClass):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = ContentActionClass(self.decision)
        activity = action.process_action()

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
        assert len(mail.outbox) == 0

        self.cinder_job.notify_reporters(action)
        action.notify_owners()
        self._test_owner_restore_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def test_target_appeal_decline(self):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = ContentActionTargetAppealRemovalAffirmation(self.decision)
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
        self.make_addon_promoted(self.rating.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
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
