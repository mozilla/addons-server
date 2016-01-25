# -*- coding: utf-8 -*-
import time
import urllib
import urlparse

from django.conf import settings

import mock
import pytest
from mock import Mock

import amo.tests
import paypal


pytestmark = pytest.mark.django_db

good_response = (
    'responseEnvelope.timestamp='
    '2011-01-28T06%3A16%3A33.259-08%3A00&responseEnvelope.ack=Success'
    '&responseEnvelope.correlationId=7377e6ae1263c'
    '&responseEnvelope.build=1655692'
    '&payKey=AP-9GD76073HJ780401K&paymentExecStatus=CREATED')

auth_error = (
    'error(0).errorId=520003'
    '&error(0).message=Authentication+failed.+API+'
    'credentials+are+incorrect.')

other_error = ('error(0).errorId=520001&error(0).message=Foo')

good_check_purchase = ('status=CREATED')  # There is more, but I trimmed it.

good_token = urllib.urlencode({'token': 'foo', 'secret': 'bar'})


class TestPayKey(amo.tests.TestCase):
    def setUp(self):
        super(TestPayKey, self).setUp()
        self.data = {'slug': 'xx',
                     'amount': 10,
                     'email': 'someone@somewhere.com',
                     'uuid': time.time(),
                     'ip': '127.0.0.1',
                     'pattern': 'addons.paypal'}
        self.pre = Mock()
        self.pre.paypal_key = 'xyz'

    def get_pre_data(self):
        data = self.data.copy()
        return data

    def test_data_fails(self):
        data = self.data.copy()
        data['amount'] = 'some random text'
        with pytest.raises(paypal.PaypalError):
            paypal.get_paykey(data)

    @mock.patch('paypal.requests.post')
    def test_auth_fails(self, opener):
        opener.return_value.text = auth_error
        with pytest.raises(paypal.AuthError):
            paypal.get_paykey(self.data)

    @mock.patch('paypal.requests.post')
    def test_get_key(self, opener):
        opener.return_value.text = good_response
        assert paypal.get_paykey(self.data) == ('AP-9GD76073HJ780401K', 'CREATED')

    @mock.patch('paypal.requests.post')
    def test_error_is_paypal(self, opener):
        opener.side_effect = ZeroDivisionError
        with pytest.raises(paypal.PaypalError):
            paypal.get_paykey(self.data)

    @mock.patch('paypal.requests.post')
    def test_error_raised(self, opener):
        opener.return_value.text = other_error.replace('520001', '589023')
        try:
            paypal.get_paykey(self.data)
        except paypal.PaypalError as error:
            assert error.id == '589023'
            assert 'The amount is too small' in str(error)
        else:
            raise ValueError('No PaypalError was raised')

    @mock.patch('paypal.requests.post')
    def test_error_one_currency(self, opener):
        opener.return_value.text = other_error.replace('520001', '559044')
        try:
            data = self.data.copy()
            data['currency'] = 'BRL'
            paypal.get_paykey(data)
        except paypal.PaypalError as error:
            assert error.id == '559044'
            assert 'Real' in str(error), str(error)
        else:
            raise ValueError('No PaypalError was raised')

    @mock.patch('paypal.requests.post')
    def test_error_no_currency(self, opener):
        opener.return_value.text = other_error.replace('520001', '559044')
        try:
            data = self.data.copy()
            paypal.get_paykey(data)
        except paypal.PaypalError as error:
            assert error.id == '559044'
        else:
            raise ValueError('No PaypalError was raised')

    @mock.patch('paypal.requests.post')
    def test_other_fails(self, opener):
        opener.return_value.text = other_error
        with pytest.raises(paypal.PaypalError):
            paypal.get_paykey(self.data)

    @mock.patch('paypal._call')
    def test_qs_passed(self, _call):
        data = self.data.copy()
        data['qs'] = {'foo': 'bar'}
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(data)
        qs = _call.call_args[0][1]['returnUrl'].split('?')[1]
        assert dict(urlparse.parse_qsl(qs))['foo'] == 'bar'

    @mock.patch.object(settings, 'SITE_URL', 'http://foo.com')
    def _test_no_mock(self):
        # Remove _ and run if you'd like to try unmocked.
        data = self.data.copy()
        data['email'] = 'andy_1318364497_biz@gmail.com'
        return paypal.get_paykey(data)

    def _test_check_purchase_no_mock(self):
        # Remove _ and run if you'd like to try this unmocked.
        key = paypal.get_paykey(self.data)
        assert paypal.check_purchase(key) == 'CREATED'

    @mock.patch('paypal._call')
    def test_usd_default(self, _call):
        _call.return_value = {'payKey': '', 'paymentExecStatus': ''}
        paypal.get_paykey(self.data)
        assert _call.call_args[0][1]['currencyCode'] == 'USD'

    @mock.patch('paypal._call')
    def test_other_currency(self, _call):
        _call.return_value = {'payKey': '', 'paymentExecStatus': ''}
        data = self.data.copy()
        data['currency'] = 'EUR'
        paypal.get_paykey(data)
        assert _call.call_args[0][1]['currencyCode'] == 'EUR'

    @mock.patch('paypal._call')
    def test_error_currency(self, _call):
        _call.side_effect = paypal.CurrencyError()
        data = self.data.copy()
        data['currency'] = 'xxx'
        with pytest.raises(paypal.CurrencyError):
            paypal.get_paykey(data)


class TestPurchase(amo.tests.TestCase):

    @mock.patch('paypal.requests.post')
    def test_check_purchase(self, opener):
        opener.return_value.text = good_check_purchase
        assert paypal.check_purchase('some-paykey') == 'CREATED'

    @mock.patch('paypal.requests.post')
    def test_check_purchase_fails(self, opener):
        opener.return_value.text = other_error
        assert paypal.check_purchase('some-paykey') is False


@mock.patch('paypal.requests.get')
def test_check_paypal_id(get):
    get.return_value.text = 'ACK=Success'
    val = paypal.check_paypal_id(u'\u30d5\u30a9\u30af\u3059\u3051')
    assert val == (True, None)


def test_nvp():
    assert paypal._nvp_dump({'foo': 'bar'}) == 'foo=bar'
    assert paypal._nvp_dump({'foo': 'ba r'}) == 'foo=ba%20r'
    assert paypal._nvp_dump({'foo': 'bar', 'bar': 'foo'}) == 'bar=foo&foo=bar'
    assert paypal._nvp_dump({'foo': ['bar', 'baa']}) == 'foo(0)=bar&foo(1)=baa'
