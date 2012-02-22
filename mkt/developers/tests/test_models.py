from datetime import datetime, timedelta

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from mkt.developers.models import ActivityLog
from users.models import UserProfile


class TestActivityLogCount(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        now = datetime.now()
        bom = datetime(now.year, now.month, 1)
        self.lm = bom - timedelta(days=1)
        self.user = UserProfile.objects.get()
        amo.set_user(self.user)

    def test_not_review_count(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_review_count(self):
        amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_review_count_few(self):
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_review_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_not_total(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.total_reviews()), 0)

    def test_total_few(self):
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_total_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_log_admin(self):
        amo.log(amo.LOG['OBJECT_EDITED'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 1)
        eq_(len(ActivityLog.objects.for_developer()), 0)

    def test_log_not_admin(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 0)
        eq_(len(ActivityLog.objects.for_developer()), 1)
