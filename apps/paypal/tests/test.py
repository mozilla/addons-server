# -*- coding: utf-8 -*-
from decimal import Decimal
import urllib
import urlparse

from django.conf import settings

import mock
from mock import Mock
from nose.tools import eq_
import time

import amo.tests
import paypal
from addons.models import Addon

good_response = ('responseEnvelope.timestamp='
            '2011-01-28T06%3A16%3A33.259-08%3A00&responseEnvelope.ack=Success'
            '&responseEnvelope.correlationId=7377e6ae1263c'
            '&responseEnvelope.build=1655692'
            '&payKey=AP-9GD76073HJ780401K&paymentExecStatus=CREATED')

auth_error = ('error(0).errorId=520003'
            '&error(0).message=Authentication+failed.+API+'
            'credentials+are+incorrect.')

other_error = ('error(0).errorId=520001&error(0).message=Foo')

good_check_purchase = ('status=CREATED')  # There is more, but I trimmed it.

good_token = urllib.urlencode({'token': 'foo', 'secret': 'bar'})


class TestPayKey(amo.tests.TestCase):
    def setUp(self):
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
        data['preapproval'] = self.pre
        return data

    def test_data_fails(self):
        data = self.data.copy()
        data['amount'] = 'some random text'
        self.assertRaises(paypal.PaypalDataError, paypal.get_paykey, data)

    @mock.patch('paypal.requests.post')
    def test_auth_fails(self, opener):
        opener.return_value.text = auth_error
        self.assertRaises(paypal.AuthError, paypal.get_paykey, self.data)

    @mock.patch('paypal.requests.post')
    def test_get_key(self, opener):
        opener.return_value.text = good_response
        eq_(paypal.get_paykey(self.data), ('AP-9GD76073HJ780401K', 'CREATED'))

    @mock.patch('paypal.requests.post')
    def test_error_is_paypal(self, opener):
        opener.side_effect = ZeroDivisionError
        self.assertRaises(paypal.PaypalError, paypal.get_paykey, self.data)

    @mock.patch('paypal.requests.post')
    def test_error_raised(self, opener):
        opener.return_value.text = other_error.replace('520001', '589023')
        try:
            paypal.get_paykey(self.data)
        except paypal.PaypalError as error:
            eq_(error.id, '589023')
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
            eq_(error.id, '559044')
            assert 'Brazilian Real' in str(error)
        else:
            raise ValueError('No PaypalError was raised')

    @mock.patch('paypal.requests.post')
    def test_error_no_currency(self, opener):
        opener.return_value.text = other_error.replace('520001', '559044')
        try:
            data = self.data.copy()
            paypal.get_paykey(data)
        except paypal.PaypalError as error:
            eq_(error.id, '559044')
        else:
            raise ValueError('No PaypalError was raised')

    @mock.patch('paypal.requests.post')
    def test_other_fails(self, opener):
        opener.return_value.text = other_error
        self.assertRaises(paypal.PaypalError, paypal.get_paykey, self.data)

    @mock.patch('paypal._call')
    def test_qs_passed(self, _call):
        data = self.data.copy()
        data['qs'] = {'foo': 'bar'}
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(data)
        qs = _call.call_args[0][1]['returnUrl'].split('?')[1]
        eq_(dict(urlparse.parse_qsl(qs))['foo'], 'bar')

    @mock.patch.object(settings, 'SITE_URL', 'http://foo.com')
    def _test_no_mock(self):
        # Remove _ and run if you'd like to try unmocked.
        data = self.data.copy()
        data['email'] = 'andy_1318364497_biz@gmail.com'
        #data['chains'] = ((13.4, 'wtf_1315341929_biz@gmail.com'),)
        return paypal.get_paykey(data)

    def _test_check_purchase_no_mock(self):
        # Remove _ and run if you'd like to try this unmocked.
        key = paypal.get_paykey(self.data)
        eq_(paypal.check_purchase(key), 'CREATED')

    def test_split(self):
        chains = ((30, 'us@moz.com'),)
        res = paypal.add_receivers(chains, 'a@a.com', Decimal('1.99'), '123')
        eq_(res['receiverList.receiver(1).amount'], '0.60')
        eq_(res['receiverList.receiver(1).email'], 'us@moz.com')
        eq_(res['receiverList.receiver(0).amount'], '1.99')
        eq_(res['receiverList.receiver(0).email'], 'a@a.com')

    def test_multiple_split(self):
        chains = ((30, 'us@moz.com'), (10, 'me@moz.com'))
        res = paypal.add_receivers(chains, 'a@a.com', Decimal('1.99'), '123')
        eq_(res['receiverList.receiver(2).amount'], '0.20')
        eq_(res['receiverList.receiver(1).amount'], '0.60')
        eq_(res['receiverList.receiver(0).amount'], '1.99')

    def test_no_split(self):
        res = paypal.add_receivers((), 'a@a.com', Decimal('1.99'), '123')
        eq_(res['receiverList.receiver(0).amount'], '1.99')

    @mock.patch('paypal._call')
    def test_dict_no_split(self, _call):
        data = self.data.copy()
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(data)
        eq_(_call.call_args[0][1]['receiverList.receiver(0).amount'], '10')

    @mock.patch('paypal._call')
    def test_dict_split(self, _call):
        data = self.data.copy()
        data['chains'] = ((13.4, 'us@moz.com'),)
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(data)
        eq_(_call.call_args[0][1]['receiverList.receiver(0).amount'], '10')
        eq_(_call.call_args[0][1]['receiverList.receiver(1).amount'], '1.34')

    def test_primary_fees(self):
        res = paypal.add_receivers((), 'a@a.com', Decimal('1.99'), '123')
        assert 'feesPayer' not in res

    def test_split_fees(self):
        chains = ((30, 'us@moz.com'),)
        res = paypal.add_receivers(chains, 'a@a.com', Decimal('1.99'), '123')
        eq_(res['feesPayer'], 'SECONDARYONLY')

    @mock.patch('paypal._call')
    def test_not_preapproval_key(self, _call):
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(self.data)
        assert 'preapprovalKey' not in _call.call_args[0][1]

    @mock.patch('paypal._call')
    def test_preapproval_key(self, _call):
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        paypal.get_paykey(self.get_pre_data())

        called = _call.call_args[0][1]
        eq_(called['preapprovalKey'], 'xyz')
        assert 'receiverList.receiver(0).paymentType' not in called

    @mock.patch('paypal._call')
    def test_preapproval_key_split(self, _call):
        _call.return_value = {'payKey': '123', 'paymentExecStatus': ''}
        data = self.get_pre_data()
        data['chains'] = ((13.4, 'us@moz.com'),)
        paypal.get_paykey(data)

        called = _call.call_args[0][1]
        assert 'receiverList.receiver(0).paymentType' not in called
        assert 'receiverList.receiver(1).paymentType' not in called

    @mock.patch('paypal._call')
    def test_preapproval_retry(self, _call):
        # Trigger an error on the preapproval and then pass.
        def error_if(*args, **kw):
            if 'preapprovalKey' in args[1]:
                raise paypal.PreApprovalError('some error')
            return {'payKey': '123', 'paymentExecStatus': ''}
        _call.side_effect = error_if
        res = paypal.get_paykey(self.get_pre_data())
        eq_(_call.call_count, 2)
        eq_(res[0], '123')

    @mock.patch('paypal._call')
    def test_preapproval_currency_retry(self, _call):
        # Trigger an error on the currency and then pass.
        def error_if(*args, **kw):
            if 'preapprovalKey' in args[1]:
                raise paypal.CurrencyError('some error')
            return {'payKey': '123', 'paymentExecStatus': ''}
        _call.side_effect = error_if
        data = self.get_pre_data()
        data['currency'] = 'BRL'
        res = paypal.get_paykey(data)
        eq_(_call.call_count, 2)
        eq_(res[0], '123')

    @mock.patch('paypal._call')
    def test_preapproval_both_fail(self, _call):
        # Trigger an error on the preapproval and then fail again.
        def error_if(*args, **kw):
            if 'preapprovalKey' in args[1]:
                raise paypal.PreApprovalError('some error')
            raise paypal.PaypalError('other error')
        _call.side_effect = error_if
        self.assertRaises(paypal.PaypalError, paypal.get_paykey,
                          self.get_pre_data())

    @mock.patch('paypal._call')
    def test_usd_default(self, _call):
        _call.return_value = {'payKey': '', 'paymentExecStatus': ''}
        paypal.get_paykey(self.data)
        eq_(_call.call_args[0][1]['currencyCode'], 'USD')

    @mock.patch('paypal._call')
    def test_other_currency(self, _call):
        _call.return_value = {'payKey': '', 'paymentExecStatus': ''}
        data = self.data.copy()
        data['currency'] = 'EUR'
        paypal.get_paykey(data)
        eq_(_call.call_args[0][1]['currencyCode'], 'EUR')

    @mock.patch('paypal._call')
    def test_error_currency(self, _call):
        _call.side_effect = paypal.CurrencyError()
        data = self.data.copy()
        data['currency'] = 'xxx'
        self.assertRaises(paypal.CurrencyError, paypal.get_paykey, data)

    def test_error_currency_junk(self):
        for v in [u'\u30ec\u30b9', 'xysxdfsfd', '¹'.decode('utf8')]:
            self.assertRaises(paypal.PaypalDataError,
                              paypal.add_receivers,
                              [], 'f@foo.com', v, '')


class TestPurchase(amo.tests.TestCase):

    @mock.patch('paypal.requests.post')
    def test_check_purchase(self, opener):
        opener.return_value.text = good_check_purchase
        eq_(paypal.check_purchase('some-paykey'), 'CREATED')

    @mock.patch('paypal.requests.post')
    def test_check_purchase_fails(self, opener):
        opener.return_value.text = other_error
        eq_(paypal.check_purchase('some-paykey'), False)


@mock.patch('paypal.requests.get')
def test_check_paypal_id(get):
    get.return_value.text = 'ACK=Success'
    val = paypal.check_paypal_id(u'\u30d5\u30a9\u30af\u3059\u3051')
    eq_(val, (True, None))


def test_nvp():
    eq_(paypal._nvp_dump({'foo': 'bar'}), 'foo=bar')
    eq_(paypal._nvp_dump({'foo': 'ba r'}), 'foo=ba%20r')
    eq_(paypal._nvp_dump({'foo': 'bar', 'bar': 'foo'}), 'bar=foo&foo=bar')
    eq_(paypal._nvp_dump({'foo': ['bar', 'baa']}), 'foo(0)=bar&foo(1)=baa')


good_refund_string = (
    'refundInfoList.refundInfo(0).receiver.amount=123.45'
    '&refundInfoList.refundInfo(0).receiver.email=bob@example.com'
    '&refundInfoList.refundInfo(0).refundFeeAmount=1.03'
    '&refundInfoList.refundInfo(0).refundGrossAmount=123.45'
    '&refundInfoList.refundInfo(0).refundNetAmount=122.42'
    '&refundInfoList.refundInfo(0).refundStatus=REFUNDED_PENDING'
    '&refundInfoList.refundInfo(1).receiver.amount=1.23'
    '&refundInfoList.refundInfo(1).receiver.email=apps@mozilla.com'
    '&refundInfoList.refundInfo(1).refundFeeAmount=0.02'
    '&refundInfoList.refundInfo(1).refundGrossAmount=1.23'
    '&refundInfoList.refundInfo(1).refundNetAmount=1.21'
    '&refundInfoList.refundInfo(1).refundStatus=REFUNDED')

good_refund_data = [{'receiver.email': 'bob@example.com',
                     'receiver.amount': '123.45',
                     'refundFeeAmount': '1.03',
                     'refundGrossAmount': '123.45',
                     'refundNetAmount': '122.42',
                     'refundStatus': 'REFUNDED_PENDING'},
                    {'receiver.email': 'apps@mozilla.com',
                     'receiver.amount': '1.23',
                     'refundFeeAmount': '0.02',
                     'refundGrossAmount': '1.23',
                     'refundNetAmount': '1.21',
                     'refundStatus': 'REFUNDED'}]

no_token_refund_string = (
    'refundInfoList.refundInfo(0).receiver.amount=123.45'
    '&refundInfoList.refundInfo(0).receiver.email=bob@example.com'
    '&refundInfoList.refundInfo(0).refundStatus=NO_API_ACCESS_TO_RECEIVER')

processing_failed_refund_string = (
'refundInfoList.refundInfo(1).receiver.amount=0.30'
'&refundInfoList.refundInfo(1).refundStatus=NO_API_ACCESS_TO_RECEIVER'
'&refundInfoList.refundInfo(1).receiver.email=andy_1318364497_biz@gmail.com'
'&refundInfoList.refundInfo(0).receiver.email=seller_1322765404_biz@gmail.com'
'&refundInfoList.refundInfo(0).refundStatus=NOT_PROCESSED')

error_refund_string = (
    'refundInfoList.refundInfo(0).receiver.amount=123.45'
    '&refundInfoList.refundInfo(0).receiver.email=bob@example.com'
    '&refundInfoList.refundInfo(0).refundStatus=REFUND_ERROR')

already_refunded_string = (
    'refundInfoList.refundInfo(0).receiver.amount=123.45'
    '&refundInfoList.refundInfo(0).receiver.email=bob@example.com'
    '&refundInfoList.refundInfo(0).refundStatus=ALREADY_REVERSED_OR_REFUNDED')


class TestRefund(amo.tests.TestCase):
    """
    Tests for making refunds.
    """

    @mock.patch('paypal.requests.post')
    def test_refund_success(self, opener):
        """
        Making refund requests returns the refund info.
        """
        opener.return_value.text = good_refund_string
        eq_(paypal.refund('fake-paykey'), good_refund_data)

    @mock.patch('paypal.requests.post')
    def test_refund_no_refund_token(self, opener):
        opener.return_value.text = no_token_refund_string
        d = paypal.refund('fake-paykey')
        eq_(d[0]['refundStatus'], 'NO_API_ACCESS_TO_RECEIVER')

    @mock.patch('paypal.requests.post')
    def test_refund_processing_failed(self, opener):
        opener.return_value.text = processing_failed_refund_string
        d = paypal.refund('fake-paykey')
        eq_(d[0]['refundStatus'], 'NO_API_ACCESS_TO_RECEIVER')

    @mock.patch('paypal.requests.post')
    def test_refund_wrong_status(self, opener):
        opener.return_value.text = error_refund_string
        with self.assertRaises(paypal.PaypalError):
            paypal.refund('fake-paykey')

    @mock.patch('paypal._call')
    def test_refund_error(self, _call):
        _call.side_effect = paypal.PaypalError
        with self.assertRaises(paypal.PaypalError):
            paypal.refund('fake-paykey')

    @mock.patch('paypal.requests.post')
    def test_refunded_already(self, opener):
        opener.return_value.text = already_refunded_string
        eq_(paypal.refund('fake-paykey')[0]['refundStatus'],
            'ALREADY_REVERSED_OR_REFUNDED')


# This data is truncated
good_personal_basic = {
        'response.personalData(0).personalDataKey':
            'http://axschema.org/contact/country/home',
        'response.personalData(0).personalDataValue': 'US',
        'response.personalData(1).personalDataValue': 'batman@gmail.com',
        'response.personalData(1).personalDataKey':
            'http://axschema.org/contact/email',
        'response.personalData(2).personalDataValue': 'man'}

good_personal_advanced = {
        'response.personalData(0).personalDataKey':
            'http://schema.openid.net/contact/street1',
        'response.personalData(0).personalDataValue': '1 Main St',
        'response.personalData(1).personalDataKey':
            'http://schema.openid.net/contact/street2',
        'response.personalData(2).personalDataValue': 'San Jose',
        'response.personalData(2).personalDataKey':
            'http://axschema.org/contact/city/home'}


@mock.patch('paypal._call')
class TestPersonalLookup(amo.tests.TestCase):

    def setUp(self):
        self.data = {'GetBasicPersonalData': good_personal_basic,
                     'GetAdvancedPersonalData': good_personal_advanced}

    def _call(self, *args, **kw):
        return self.data[args[0]]

    def test_preapproval_works(self, _call):
        _call.side_effect = self._call
        eq_(paypal.get_personal_data('foo')['email'], 'batman@gmail.com')
        eq_(_call.call_count, 2)

    def test_preapproval_absent(self, _call):
        _call.side_effect = self._call
        eq_(paypal.get_personal_data('foo')['address_two'], '')

    def test_preapproval_unicode(self, _call):
        key = 'response.personalData(2).personalDataValue'
        value = u'Österreich'
        self.data['GetAdvancedPersonalData'][key] = value
        _call.side_effect = self._call
        eq_(paypal.get_personal_data('foo')['city'], value)

    def test_preapproval_error(self, _call):
        _call.side_effect = paypal.PaypalError
        self.assertRaises(paypal.PaypalError, paypal.get_personal_data, 'foo')


@mock.patch('paypal.requests.post')
@mock.patch.object(settings, 'PAYPAL_EMBEDDED_AUTH',
                   {'USER': 'a', 'PASSWORD': 'b', 'SIGNATURE': 'c'})
class TestAuthWithToken(amo.tests.TestCase):

    def test_token_header(self, opener):
        opener.return_value.text = good_response
        paypal._call('http://some.url', {}, token=good_token)
        assert 'X-PAYPAL-AUTHORIZATION' in opener.call_args[1]['headers']

    def test_normal_header(self, opener):
        opener.return_value.text = good_response
        paypal._call('http://some.url', {})
        assert 'X-PAYPAL-SECURITY-PASSWORD' in opener.call_args[1]['headers']
