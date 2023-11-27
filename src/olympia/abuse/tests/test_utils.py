from django.conf import settings

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderJob
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

from ..utils import (
    CinderActionApproveAppealOverride,
    CinderActionApproveInitialDecision,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
)


class TestCinderAction(TestCase):
    def setUp(self):
        self.cinder_job = CinderJob.objects.create(job_id='1234')
        AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid='1234',
            cinder_job=self.cinder_job,
        )
        AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid='1234',
            cinder_job=self.cinder_job,
        )
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        # It's the webhook's responsability to do this before calling the
        # action. We need it for the ActivityLog creation to work.
        set_user(self.task_user)

    def test_ban_user(self):
        user = user_factory()
        self.cinder_job.abusereport_set.update(user=user, guid=None)
        action = CinderActionBanUser(self.cinder_job)
        action.process()
        user.reload()
        self.assertCloseToNow(user.banned)
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_BANNED.id)
        assert activity.arguments == [user]
        assert activity.user == self.task_user

    def test_approve_user(self):
        user = user_factory(banned=self.days_ago(1), deleted=True)
        self.cinder_job.abusereport_set.update(user=user, guid=None)
        action = CinderActionApproveAppealOverride(self.cinder_job)
        action.process()
        user.reload()
        assert not user.banned
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.ADMIN_USER_UNBAN.id)
        assert activity.arguments == [user]
        assert activity.user == self.task_user

    def test_disable_addon(self):
        addon = addon_factory()
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=addon.guid)
        action = CinderActionDisableAddon(self.cinder_job)
        action.process()
        assert addon.reload().status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.FORCE_DISABLE.id)
        assert activity.arguments == [addon]
        assert activity.user == self.task_user

    def test_approve_appeal_addon(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=addon.guid)
        action = CinderActionApproveAppealOverride(self.cinder_job)
        action.process()
        assert addon.reload().status == amo.STATUS_NULL
        assert ActivityLog.objects.count() == 2  # Extra because of status change.
        activity = ActivityLog.objects.get(action=amo.LOG.FORCE_ENABLE.id)
        assert activity.arguments == [addon]
        assert activity.user == self.task_user

    def test_approve_initial_addon(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=addon.guid)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()
        assert addon.reload().status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 0

    def test_escalate_addon(self):
        addon = addon_factory(file_kw={'is_signed': True})
        listed_version = addon.current_version
        unlisted_version = version_factory(
            addon=addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(guid=addon.guid)
        action = CinderActionEscalateAddon(self.cinder_job)
        action.process()
        assert addon.reload().status == amo.STATUS_APPROVED
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
            addon=addon, file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
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

    def test_delete_collection(self):
        collection = collection_factory(author=user_factory())
        self.cinder_job.abusereport_set.update(collection=collection, guid=None)
        action = CinderActionDeleteCollection(self.cinder_job)
        action.process()
        assert collection.reload()
        assert collection.deleted
        assert collection.slug
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_DELETED.id)
        assert activity.arguments == [collection]
        assert activity.user == self.task_user

    def test_approve_initial_collection(self):
        collection = collection_factory(author=user_factory(), deleted=True)
        self.cinder_job.abusereport_set.update(collection=collection, guid=None)
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()
        assert collection.reload()
        assert collection.deleted
        assert ActivityLog.objects.count() == 0

    def test_approve_appeal_collection(self):
        collection = collection_factory(author=user_factory(), deleted=True)
        self.cinder_job.abusereport_set.update(collection=collection, guid=None)
        action = CinderActionApproveAppealOverride(self.cinder_job)
        action.process()
        assert collection.reload()
        assert not collection.deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.COLLECTION_UNDELETED.id)
        assert activity.arguments == [collection]
        assert activity.user == self.task_user

    def test_delete_rating(self):
        rating = Rating.objects.create(addon=addon_factory(), user=user_factory())
        self.cinder_job.abusereport_set.update(rating=rating, guid=None)
        ActivityLog.objects.all().delete()
        action = CinderActionDeleteRating(self.cinder_job)
        action.process()
        assert rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.DELETE_RATING.id)
        assert activity.arguments == [rating.addon, rating]
        assert activity.user == self.task_user

    def test_approve_initial_rating(self):
        rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), deleted=True
        )
        self.cinder_job.abusereport_set.update(rating=rating, guid=None)
        ActivityLog.objects.all().delete()
        action = CinderActionApproveInitialDecision(self.cinder_job)
        action.process()
        assert rating.reload().deleted
        assert ActivityLog.objects.count() == 0

    def test_approve_appeal_rating(self):
        rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), deleted=True
        )
        ActivityLog.objects.all().delete()
        self.cinder_job.abusereport_set.update(rating=rating, guid=None)
        action = CinderActionApproveAppealOverride(self.cinder_job)
        action.process()
        assert not rating.reload().deleted
        assert ActivityLog.objects.count() == 1
        activity = ActivityLog.objects.get(action=amo.LOG.UNDELETE_RATING.id)
        assert activity.arguments == [rating, rating.addon]
        assert activity.user == self.task_user
