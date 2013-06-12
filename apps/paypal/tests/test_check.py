from decimal import Decimal

from mock import Mock, patch
from nose.tools import eq_

import amo
import amo.tests
from paypal.check import Check
from paypal import PaypalError


class TestCheck(amo.tests.TestCase):

    def setUp(self):
        self.addon = Mock()
        self.addon.paypal_id = 'foo@bar.com'
        self.addon.premium.paypal_permission_token = 'foo'
        self.addon.premium.price.price = Decimal('1.00')
        self.addon.premium.price._currencies = {}
        self.usd = Mock()
        self.usd.price = Decimal('1.0')
        self.currency = Mock()
        self.currency.currency = 'EUR'
        self.currency.price = Decimal('0.5')
        self.check = Check(addon=self.addon)

    def test_uses_addon(self):
        self.check = Check(addon=self.addon)
        eq_(self.check.paypal_id, self.addon.paypal_id)
        self.check = Check(addon=self.addon, paypal_id='goo@bar.com')
        eq_(self.check.paypal_id, 'goo@bar.com')

    @patch('paypal.check_paypal_id')
    def test_check_id_pass(self, check_paypal_id):
        check_paypal_id.return_value = True, ''
        self.check.check_id()
        assert self.check.passed, self.check.state

    @patch('paypal.check_paypal_id')
    def test_check_id_fail(self, check_paypal_id):
        check_paypal_id.return_value = False, ''
        self.check.check_id()
        assert not self.check.passed, self.check.state

    def test_check_id_none(self):
        self.check.paypal_id = None
        self.check.check_id()
        assert not self.check.passed, self.check.state
