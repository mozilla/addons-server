from django.conf import settings

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderReport
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.reviewers.models import NeedsHumanReview

from ..utils import (
    CinderActionApprove,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
)


class TestCinderAction(TestCase):
    def setUp(self):
        abuse_report = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE, guid='1234'
        )
        self.cinder_report = CinderReport.objects.create(
            job_id='1234', abuse_report=abuse_report
        )

    def test_ban_user(self):
        user = user_factory()
        self.cinder_report.abuse_report.update(user=user, guid=None)
        action = CinderActionBanUser(self.cinder_report)
        action.process()
        self.assertCloseToNow(user.banned)

    def test_disable_addon(self):
        addon = addon_factory()
        self.cinder_report.abuse_report.update(guid=addon.guid)
        action = CinderActionDisableAddon(self.cinder_report)
        action.process()
        assert addon.reload().status == amo.STATUS_DISABLED

    def test_approve_addon(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        self.cinder_report.abuse_report.update(guid=addon.guid)
        action = CinderActionApprove(self.cinder_report)
        action.process()
        assert addon.reload().status == amo.STATUS_NULL

    def test_escalate_addon(self):
        user_factory(id=settings.TASK_USER_ID)
        addon = addon_factory(file_kw={'is_signed': True})
        listed_version = addon.current_version
        unlisted_version = version_factory(
            addon=addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': True}
        )
        self.cinder_report.abuse_report.update(guid=addon.guid)
        action = CinderActionEscalateAddon(self.cinder_report)
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

        # but if we have a version specified, we flag that version
        NeedsHumanReview.objects.all().delete()
        other_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        self.cinder_report.abuse_report.update(addon_version=other_version.version)
        action.process()
        assert not listed_version.reload().needshumanreview_set.exists()
        assert not unlisted_version.reload().needshumanreview_set.exists()
        assert (
            other_version.reload().needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_CINDER_ESCALATION
        )

    def test_delete_collection(self):
        collection = collection_factory(author=user_factory())
        self.cinder_report.abuse_report.update(collection=collection, guid=None)
        action = CinderActionDeleteCollection(self.cinder_report)
        action.process()
        assert collection.deleted
        assert collection.slug

    def test_approve_collection(self):
        collection = collection_factory(author=user_factory(), deleted=True)
        self.cinder_report.abuse_report.update(collection=collection, guid=None)
        action = CinderActionApprove(self.cinder_report)
        action.process()
        assert not collection.deleted
