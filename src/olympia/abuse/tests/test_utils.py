from datetime import datetime

from django.conf import settings
from django.core import mail
from django.urls import reverse

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.core import set_user
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview

from ..models import AbuseReport, CinderJob, CinderPolicy
from ..utils import (
    CinderActionApproveInitialDecision,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionOverrideApprove,
    CinderActionTargetAppealApprove,
    CinderActionTargetAppealRemovalAffirmation,
)


class BaseTestCinderAction:
    def setUp(self):
        self.cinder_job = CinderJob.objects.create(
            job_id='1234', decision_id='ab89', decision_date=datetime.now()
        )
        self.cinder_job.policies.add(
            CinderPolicy.objects.create(
                uuid='1234', name='Bad policy', text='This is bad thing'
            )
        )
        self.abuse_report_no_auth = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid='1234',
            cinder_job=self.cinder_job,
            reporter_email='email@domain.com',
        )
        self.abuse_report_auth = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid='1234',
            cinder_job=self.cinder_job,
            reporter=user_factory(),
        )
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        # It's the webhook's responsability to do this before calling the
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
        assert 'action to remove' in mail.outbox[0].body
        assert 'action to remove' in mail.outbox[1].body
        assert 'appeal' not in mail.outbox[0].body
        assert 'appeal' not in mail.outbox[1].body
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[1].body

    def _test_reporter_ignore_email(self, subject):
        assert mail.outbox[0].to == ['email@domain.com']
        assert mail.outbox[1].to == [self.abuse_report_auth.reporter.email]
        assert mail.outbox[0].subject == (
            subject + f' [ref:ab89/{self.abuse_report_no_auth.id}]'
        )
        assert mail.outbox[1].subject == (
            subject + f' [ref:ab89/{self.abuse_report_auth.id}]'
        )
        assert 'does not violate our add-on policies' in mail.outbox[0].body
        assert 'does not violate our add-on policies' in mail.outbox[1].body
        assert (
            reverse(
                'abuse.appeal_reporter',
                kwargs={
                    'abuse_report_id': self.abuse_report_no_auth.id,
                    'decision_id': self.cinder_job.decision_id,
                },
            )
            in mail.outbox[0].body
        )
        assert (
            reverse(
                'abuse.appeal_reporter',
                kwargs={
                    'abuse_report_id': self.abuse_report_auth.id,
                    'decision_id': self.cinder_job.decision_id,
                },
            )
            in mail.outbox[1].body
        )
        assert f'[ref:ab89/{self.abuse_report_no_auth.id}]' in mail.outbox[0].body
        assert f'[ref:ab89/{self.abuse_report_auth.id}]' in mail.outbox[1].body

    def _check_owner_email(self, mail_item, subject, snippet):
        user = getattr(self, 'user', getattr(self, 'author', None))
        assert mail_item.to == [user.email]
        assert mail_item.subject == subject + ' [ref:ab89]'
        assert snippet in mail_item.body
        assert '[ref:ab89]' in mail_item.body

    def _test_owner_takedown_email(self, subject, snippet):
        mail_item = mail.outbox[2]
        self._check_owner_email(mail_item, subject, snippet)
        assert 'right to appeal' in mail_item.body
        assert (
            reverse(
                'abuse.appeal_author',
                kwargs={
                    'decision_id': self.cinder_job.decision_id,
                },
            )
            in mail_item.body
        )
        assert 'Bad policy' in mail_item.body

    def _test_owner_affirmation_email(self, subject):
        mail_item = mail.outbox[0]
        self._check_owner_email(mail_item, subject, 'was correct')
        assert 'right to appeal' not in mail_item.body
        assert 'Bad policy' in mail_item.body

    def _test_owner_restore_email(self, subject):
        mail_item = mail.outbox[0]
        assert len(mail.outbox) == 1
        self._check_owner_email(mail_item, subject, 'we have restored')
        assert 'right to appeal' not in mail_item.body

    def _test_approve_appeal_override(CinderActionClass):
        raise NotImplementedError

    def test_approve_appeal_success(self):
        self._test_approve_appeal_override(CinderActionTargetAppealApprove)
        assert 'in response to your appeal' in mail.outbox[0].body

    def test_approve_override(self):
        self._test_approve_appeal_override(CinderActionOverrideApprove)
        assert 'in response to your appeal' not in mail.outbox[0].body


class TestCinderActionUser(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionBanUser

    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.cinder_job.abusereport_set.update(user=self.user, guid=None)

    def test_ban_user(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_BAN_USER)
        action = self.ActionClass(self.cinder_job)
        action.process()

        self.user.reload()
        self.assertCloseToNow(self.user.banned)
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_BANNED.id)
        assert activity.arguments == [self.user]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 3
        subject = f'Mozilla Add-ons: {self.user.name}'
        self._test_owner_takedown_email(subject, 'has been suspended')
        self._test_reporter_takedown_email(subject)

    def test_approve_initial(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()

        self.user.reload()
        assert not self.user.banned
        assert len(mail.outbox) == 2
        self._test_reporter_ignore_email(f'Mozilla Add-ons: {self.user.name}')

    def _test_approve_appeal_override(self, CinderActionClass):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        self.user.update(banned=self.days_ago(1), deleted=True)
        CinderActionClass(self.cinder_job).process()

        self.user.reload()
        assert not self.user.banned
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_UNBAN.id)
        assert activity.arguments == [self.user]
        assert activity.user == self.task_user
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.user.name}')

    def test_approve_appeal_decline(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        self.user.update(banned=self.days_ago(1), deleted=True)
        action = CinderActionTargetAppealRemovalAffirmation(self.cinder_job)
        action.process()

        self.user.reload()
        assert self.user.banned
        assert ActivityLog.objects.count() == 0
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.user.name}')


class TestCinderActionAddon(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDisableAddon

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.addon = addon_factory(users=(self.author,))
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=self.addon.guid)

    def test_disable_addon(self):
        self.cinder_job.update(
            decision_action=CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON
        )
        action = self.ActionClass(self.cinder_job)
        action.process()

        assert self.addon.reload().status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.FORCE_DISABLE.id)
        assert activity.arguments == [self.addon]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 3
        subject = f'Mozilla Add-ons: {self.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently disabled')
        assert f'Your Extension {self.addon.name}' in mail.outbox[2].body
        self._test_reporter_takedown_email(subject)

    def _test_approve_appeal_override(self, CinderActionClass):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = CinderActionClass(self.cinder_job)
        action.process()

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.FORCE_ENABLE.id)
        assert activity.arguments == [self.addon]
        assert activity.user == self.task_user
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_approve_initial(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 2
        self._test_reporter_ignore_email(f'Mozilla Add-ons: {self.addon.name}')

    def test_escalate_addon(self):
        listed_version = self.addon.current_version
        listed_version.file.update(is_signed=True)
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        ActivityLog.objects.all().delete()
        action = CinderActionEscalateAddon(self.cinder_job)
        action.process()

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert (
            listed_version.reload().needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert (
            unlisted_version.reload().needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert ActivityLog.objects.count() == 2
        activity = ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        ).order_by('pk')[0]
        assert activity.arguments == [listed_version]
        assert activity.user == self.task_user
        activity = ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        ).order_by('pk')[1]
        assert activity.arguments == [unlisted_version]
        assert activity.user == self.task_user

        # but if we have a version specified, we flag that version
        NeedsHumanReview.objects.all().delete()
        other_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        assert not other_version.due_date
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(addon_version=other_version.version)
        action.process()
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.reload().needshumanreview_set.exists()
        other_version.reload()
        assert other_version.due_date
        assert (
            other_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        )
        assert activity.arguments == [other_version]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 0

    def test_approve_appeal_decline(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        action = CinderActionTargetAppealRemovalAffirmation(self.cinder_job)
        action.process()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.addon.name}')


class TestCinderActionCollection(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDeleteCollection

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.collection = collection_factory(author=self.author)
        self.cinder_job.abusereport_set.update(collection=self.collection, guid=None)

    def test_delete_collection(self):
        self.cinder_job.update(
            decision_action=CinderJob.DECISION_ACTIONS.AMO_DELETE_COLLECTION
        )
        action = self.ActionClass(self.cinder_job)
        action.process()

        assert self.collection.reload()
        assert self.collection.deleted
        assert self.collection.slug
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_DELETED.id)
        assert activity.arguments == [self.collection]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 3
        subject = f'Mozilla Add-ons: {self.collection.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        self._test_reporter_takedown_email(subject)

    def test_approve_initial(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 0
        assert len(mail.outbox) == 2
        self._test_reporter_ignore_email(f'Mozilla Add-ons: {self.collection.name}')

    def _test_approve_appeal_override(self, CinderActionClass):
        self.collection.update(deleted=True)
        action = CinderActionClass(self.cinder_job)
        action.process()

        assert self.collection.reload()
        assert not self.collection.deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_UNDELETED.id)
        assert activity.arguments == [self.collection]
        assert activity.user == self.task_user
        self._test_owner_restore_email(f'Mozilla Add-ons: {self.collection.name}')

    def test_approve_appeal_decline(self):
        self.collection.update(deleted=True)
        action = CinderActionTargetAppealRemovalAffirmation(self.cinder_job)
        action.process()

        self.collection.reload()
        assert self.collection.deleted
        assert ActivityLog.objects.count() == 0
        self._test_owner_affirmation_email(f'Mozilla Add-ons: {self.collection.name}')


class TestCinderActionRating(BaseTestCinderAction, TestCase):
    ActionClass = CinderActionDeleteRating

    def setUp(self):
        super().setUp()
        self.author = user_factory()
        self.rating = Rating.objects.create(
            addon=addon_factory(), user=self.author, body='Saying something bad'
        )
        self.cinder_job.abusereport_set.update(rating=self.rating, guid=None)
        ActivityLog.objects.all().delete()

    def test_delete_rating(self):
        self.cinder_job.update(
            decision_action=CinderJob.DECISION_ACTIONS.AMO_DELETE_RATING
        )
        action = self.ActionClass(self.cinder_job)
        action.process()

        assert self.rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.DELETE_RATING.id)
        assert activity.arguments == [self.rating.addon, self.rating]
        assert activity.user == self.task_user
        assert len(mail.outbox) == 3
        subject = f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        self._test_owner_takedown_email(subject, 'permanently removed')
        self._test_reporter_takedown_email(subject)

    def test_approve_initial(self):
        self.cinder_job.update(decision_action=CinderJob.DECISION_ACTIONS.AMO_APPROVE)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()

        assert not self.rating.reload().deleted
        assert len(mail.outbox) == 2
        assert ActivityLog.objects.count() == 0
        self._test_reporter_ignore_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def _test_approve_appeal_override(self, CinderActionClass):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = CinderActionClass(self.cinder_job)
        action.process()

        assert not self.rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.UNDELETE_RATING.id)
        assert activity.arguments == [self.rating, self.rating.addon]
        assert activity.user == self.task_user
        self._test_owner_restore_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )

    def test_approve_appeal_decline(self):
        self.rating.delete()
        ActivityLog.objects.all().delete()
        action = CinderActionTargetAppealRemovalAffirmation(self.cinder_job)
        action.process()

        self.rating.reload()
        assert self.rating.deleted
        assert ActivityLog.objects.count() == 0
        self._test_owner_affirmation_email(
            f'Mozilla Add-ons: "Saying ..." for {self.rating.addon.name}'
        )
