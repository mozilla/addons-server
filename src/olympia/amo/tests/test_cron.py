from nose.tools import eq_

from olympia.amo.tests import TestCase
from olympia.amo.cron import gc
from olympia.bandwagon.models import Collection
from olympia.devhub.models import ActivityLog
from olympia.stats.models import AddonShareCount, Contribution


class GarbageTest(TestCase):
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
