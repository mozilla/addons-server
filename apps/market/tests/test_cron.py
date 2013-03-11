from datetime import datetime, timedelta

from nose.tools import eq_

import amo
import amo.tests

from addons.models import Addon
from devhub.models import ActivityLog
from market.cron import clean_out_addonpremium, mkt_gc
from market.models import AddonPremium
from users.models import UserProfile


class TestCronDeletes(amo.tests.TestCase):

    def setUp(self):
        for x in xrange(0, 3):
            addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
            premium = AddonPremium.objects.create(addon=addon)
            premium.update(created=datetime.today() -
                                   timedelta(days=x, seconds=5))

    def test_delete(self):
        eq_(AddonPremium.objects.count(), 3)
        clean_out_addonpremium(days=2)
        eq_(AddonPremium.objects.count(), 2)
        clean_out_addonpremium(days=1)
        eq_(AddonPremium.objects.count(), 1)

    def test_doesnt_delete(self):
        Addon.objects.all().update(premium_type=amo.ADDON_PREMIUM)
        clean_out_addonpremium(days=1)
        eq_(AddonPremium.objects.count(), 3)


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
