from datetime import datetime, timedelta

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from market.models import AddonPremium
from market.cron import clean_out_addonpremium


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

