from olympia import amo
from olympia.abuse.models import AbuseReport, CinderReport
from olympia.amo.tests import TestCase, addon_factory, user_factory

from ..utils import CinderActionApprove, CinderActionBanUser, CinderActionDisableAddon


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

    def test_approved_addon(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        self.cinder_report.abuse_report.update(guid=addon.guid)
        action = CinderActionApprove(self.cinder_report)
        action.process()
        assert addon.reload().status == amo.STATUS_NULL
