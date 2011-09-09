from cStringIO import StringIO

from django.conf import settings

import mock
from nose.tools import eq_
import time

from addons.models import Addon
import amo.tests
import paypal


good_response = ('responseEnvelope.timestamp='
            '2011-01-28T06%3A16%3A33.259-08%3A00&responseEnvelope.ack=Success'
            '&responseEnvelope.correlationId=7377e6ae1263c'
            '&responseEnvelope.build=1655692'
            '&payKey=AP-9GD76073HJ780401K&paymentExecStatus=CREATED')

auth_error = ('error(0).errorId=520003'
            '&error(0).message=Authentication+failed.+API+'
            'credentials+are+incorrect.')

other_error = ('error(0).errorId=520001'
            '&error(0).message=Foo')

good_check_purchase = ('status=CREATED')  # There is more, but I trimmed it.


class TestPayKey(amo.tests.TestCase):
    def setUp(self):
        self.data = {'slug': 'xx',
                     'amount': 10,
                     'email': 'someone@somewhere.com',
                     'uuid': time.time(),
                     'ip': '127.0.0.1',
                     'pattern': 'addons.purchase.finished'}

    @mock.patch('urllib2.OpenerDirector.open')
    def test_auth_fails(self, opener):
        opener.return_value = StringIO(auth_error)
        self.assertRaises(paypal.AuthError, paypal.get_paykey, self.data)

    @mock.patch('urllib2.OpenerDirector.open')
    def test_get_key(self, opener):
        opener.return_value = StringIO(good_response)
        eq_(paypal.get_paykey(self.data), 'AP-9GD76073HJ780401K')

    @mock.patch('urllib2.OpenerDirector.open')
    def test_other_fails(self, opener):
        opener.return_value = StringIO(other_error)
        self.assertRaises(paypal.PaypalError, paypal.get_paykey, self.data)

    def _test_no_mock(self):
        # Remove _ and run if you'd like to try unmocked.
        return paypal.get_paykey(self.data)

    def _test_check_purchase_no_mock(self):
        # Remove _ and run if you'd like to try this unmocked.
        key = paypal.get_paykey(self.data)
        eq_(paypal.check_purchase(key), 'CREATED')


class TestPurchase(amo.tests.TestCase):

    @mock.patch('urllib2.OpenerDirector.open')
    def test_check_purchase(self, opener):
        opener.return_value = StringIO(good_check_purchase)
        eq_(paypal.check_purchase('some-paykey'), 'CREATED')

    @mock.patch('urllib2.OpenerDirector.open')
    def test_check_purchase_fails(self, opener):
        opener.return_value = StringIO(other_error)
        eq_(paypal.check_purchase('some-paykey'), False)


@mock.patch('paypal.urllib.urlopen')
def test_check_paypal_id(urlopen_mock):
    urlopen_mock.return_value = StringIO('ACK=Success')
    val = paypal.check_paypal_id(u'\u30d5\u30a9\u30af\u3059\u3051')
    eq_(val, (True, None))


@mock.patch('paypal._call')
@mock.patch.object(settings, 'PAYPAL_PERMISSIONS_URL', 'something')
class TestRefundPermissions(amo.tests.TestCase):

    def test_refund_permissions_url(self, _call):
        """
        `paypal_refund_permission_url` returns an URL for PayPal's
        permissions request service containing the token PayPal gives
        us.
        """
        _call.return_value = {'token': 'foo'}
        addon = Addon(type=amo.ADDON_EXTENSION, slug='foo')
        assert 'foo' in paypal.refund_permission_url(addon)

    def test_check_refund_permission_fail(self, _call):
        """
        `check_paypal_refund_permission` returns False if PayPal
        doesn't put 'REFUND' in the permissions response.
        """
        _call.return_value = {'scope(0)': 'HAM_SANDWICH'}
        assert not paypal.check_refund_permission('foo')

    def test_check_refund_permission(self, _call):
        """
        `check_paypal_refund_permission` returns True if PayPal
        puts 'REFUND' in the permissions response.
        """
        _call.return_value = {'scope(0)': 'REFUND'}
        eq_(paypal.check_refund_permission('foo'), True)

    def test_get_permissions_token(self, _call):
        _call.return_value = {'token': 'FOO'}
        eq_(paypal.get_permissions_token('foo', ''), 'FOO')
