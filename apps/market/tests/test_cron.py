from datetime import datetime

from nose.tools import eq_

import amo
import amo.tests

from devhub.models import ActivityLog
from market.cron import mkt_gc
from users.models import UserProfile


class TestGarbage(amo.tests.TestCase):

    def setUp(self):
        self.user = UserProfile.objects.create(email='gc_test@example.com',
                name='gc_test')
        amo.log(amo.LOG.CUSTOM_TEXT, 'testing', user=self.user,
                created=datetime(2001, 1, 1))

    def test_garbage_collection(self):
        eq_(ActivityLog.objects.all().count(), 1)
        mkt_gc()
        eq_(ActivityLog.objects.all().count(), 0)
