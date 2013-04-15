from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from market.models import AddonPremium, Price
from market.forms import PriceCurrencyForm


class TestForm(amo.tests.TestCase):
    fixtures = ['market/prices', 'base/addon_3615']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)
        self.addon = Addon.objects.get(pk=3615)
        self.addon_premium = AddonPremium.objects.create(addon=self.addon,
                                                         price=self.tier_one)

    def test_form_passes(self):
        for currency, valid in (['EUR', True], ['BRL', False], ['CAD', True]):
            form = PriceCurrencyForm(data={'currency': currency},
                                     addon=self.addon)
            eq_(bool(form.is_valid()), valid, 'Currency: %s' % currency)
