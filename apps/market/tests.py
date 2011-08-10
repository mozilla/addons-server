from nose.tools import eq_

import amo
import amo.tests

from market.models import Price


class TestPrice(amo.tests.TestCase):
    fixtures = ['prices.json']

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)
