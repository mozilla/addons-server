from nose.tools import eq_

import amo.tests
from amo.cron import gc
from bandwagon.models import Collection
from devhub.models import ActivityLog
from stats.models import AddonShareCount, Contribution


class GarbageTest(amo.tests.TestCase):
    fixtures = ['base/addon_59', 'base/garbage']

    def test_garbage_collection(self):
        "This fixture is expired data that should just get cleaned up."
        eq_(Collection.objects.all().count(), 1)
        eq_(ActivityLog.objects.all().count(), 1)
        eq_(AddonShareCount.objects.all().count(), 1)
        eq_(Contribution.objects.all().count(), 1)
        gc(test_result=False)
        eq_(Collection.objects.all().count(), 0)
        eq_(ActivityLog.objects.all().count(), 0)
        eq_(AddonShareCount.objects.all().count(), 0)
        eq_(Contribution.objects.all().count(), 0)
