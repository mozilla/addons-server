import test_utils
from nose.tools import eq_

from amo.cron import gc
from bandwagon.models import Collection
from cake.models import Session
from devhub.models import ActivityLog
from files.models import TestResult, TestResultCache
from stats.models import AddonShareCount, Contribution


class GarbageTest(test_utils.TestCase):
    fixtures = ['base/addon_59', 'base/garbage']

    def test_garbage_collection(self):
        "This fixture is expired data that should just get cleaned up."
        eq_(Collection.objects.all().count(), 1)
        eq_(Session.objects.all().count(), 1)
        eq_(ActivityLog.objects.all().count(), 1)
        eq_(TestResult.objects.all().count(), 1)
        eq_(TestResultCache.objects.all().count(), 1)
        eq_(AddonShareCount.objects.all().count(), 1)
        eq_(Contribution.objects.all().count(), 1)
        gc(test_result=False)
        eq_(Collection.objects.all().count(), 0)
        eq_(Session.objects.all().count(), 0)
        eq_(ActivityLog.objects.all().count(), 0)
        eq_(TestResultCache.objects.all().count(), 0)
        eq_(AddonShareCount.objects.all().count(), 0)
        eq_(Contribution.objects.all().count(), 0)
