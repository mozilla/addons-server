from nose.tools import eq_

import amo
import amo.tests

from market.models import Price


class TestPrice(amo.tests.TestCase):
    fixtures = ['prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)

    def test_currency(self):
        eq_(self.tier_one.pricecurrency_set.count(), 2)
