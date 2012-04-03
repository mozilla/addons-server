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
        self.addon.premium.supported_currencies.return_value = (
                ['USD', self.usd], ['EUR', self.currency])
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

    @patch('paypal.check_permission')
    def test_check_refund(self, check_permission):
        check_permission.return_value = True
        self.check.check_refund()
        assert self.check.passed, self.check.state

    @patch('paypal.check_permission')
    def test_check_refund_fails(self, check_permission):
        check_permission.return_value = False
        self.check.check_refund()
        assert not self.check.passed, self.check.state

    def test_check_refund_no_token(self):
        self.addon.premium.paypal_permission_token = ''
        self.check.check_refund()
        assert not self.check.passed, self.check.state

    def test_check_refund_no_premium(self):
        self.addon.premium = None
        self.check.check_refund()
        assert not self.check.passed, self.check.state

    @patch('paypal.get_paykey')
    def test_check_paykey(self, get_paykey):
        self.check.check_currencies()
        eq_(get_paykey.call_args_list[0][0][0]['currency'], 'USD')
        eq_(get_paykey.call_args_list[1][0][0]['currency'], 'EUR')
        assert self.check.passed, self.check.state

    @patch('paypal.get_paykey')
    def test_check_paykey_no_premium(self, get_paykey):
        self.addon.premium = None
        self.check.check_currencies()
        eq_(len(get_paykey.call_args_list), 1)
        assert self.check.passed, self.check.state

    @patch('paypal.get_paykey')
    def test_check_paykey_currencies(self, get_paykey):
        self.check.check_currencies()
        eq_(len(get_paykey.call_args_list), 2)
        eq_([c[0][0]['currency'] for c in get_paykey.call_args_list],
            ['USD', 'EUR'])
        assert self.check.passed, self.check.state

    @patch('paypal.get_paykey')
    def test_check_price_none(self, get_paykey):
        self.addon.premium.price = None
        self.check.check_currencies()
        eq_(len(get_paykey.call_args_list), 1)
        eq_(get_paykey.call_args[0][0]['amount'], '1.00')

    @patch('paypal.get_paykey')
    def test_check_paykey_fails(self, get_paykey):
        premium = self.addon.premium
        for cr in ['USD', 'NaN']:
            self.check = Check(addon=self.addon)
            premium.supported_currencies.return_value = ([cr, self.usd],)
            get_paykey.side_effect = PaypalError()
            self.check.check_currencies()
            assert not self.check.passed, self.check.state
            eq_(self.check.errors,
                ['Failed to make a test transaction in %s.' % cr])
