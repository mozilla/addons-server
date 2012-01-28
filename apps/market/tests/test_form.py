from decimal import Decimal
import json


import mock
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import AddonPremium, PreApprovalUser, Price, PriceCurrency
from stats.models import Contribution
from users.models import UserProfile

from django.utils import translation
from market.forms import PriceCurrencyForm


class TestForm(amo.tests.TestCase):
    fixtures = ['prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)

    def test_form(self):
        for currency, valid in (['EUR', True], ['CAD', True], ['BRL', False]):
            form = PriceCurrencyForm(data={'currency': currency},
                                     price=self.tier_one)
            eq_(bool(form.is_valid()), valid)
