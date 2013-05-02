from StringIO import StringIO

from nose.tools import eq_

import amo.tests

from market.models import Price, PriceCurrency
from market.utils import update, update_from_csv

tiers = [
    {'USD': '0.99', 'BRL': '1.99'},
    # This row should be ignored, no tier of value 3.
    {'USD': '3.00'},
    # This row should be ignored, not US tier.
    {'CAD': '10'}
]

csv = StringIO("""USD\tCAD\tBRL\n0.99\t1.99\t1.00""")

class TestUpdate(amo.tests.TestCase):

    def setUp(self):
        self.tier = Price.objects.create(name='1', price='0.99')

    def test_create(self):
        update(tiers)
        eq_(str(PriceCurrency.objects.get(currency='BRL').price), '1.99')
        assert not PriceCurrency.objects.filter(currency='CAD').exists()

    def test_update(self):
        PriceCurrency.objects.create(currency='BRL', tier=self.tier, price='2')
        update(tiers)
        eq_(str(PriceCurrency.objects.get(currency='BRL').price), '1.99')

    def test_csv(self):
        update_from_csv(csv)
        assert PriceCurrency.objects.filter(currency='CAD').exists()
