from cStringIO import StringIO

from amo.urlresolvers import reverse
from amo.helpers import absolutify

import mock
from nose.tools import eq_
import test_utils
import time

import paypal


good_response = ('responseEnvelope.timestamp='
            '2011-01-28T06%3A16%3A33.259-08%3A00&responseEnvelope.ack=Success'
            '&responseEnvelope.correlationId=7377e6ae1263c'
            '&responseEnvelope.build=1655692'
            '&payKey=AP-9GD76073HJ780401K&paymentExecStatus=CREATED')

auth_error = ('error(0).errorId=520003'
            '&error(0).message=Authentication+failed.+API+'
            'credentials+are+incorrect.')


class TestPayPal(test_utils.TestCase):
    def setUp(self):
        self.data = {'return_url': absolutify(reverse('home')),
                     'cancel_url': absolutify(reverse('home')),
                     'amount': 10,
                     'email': 'someone@somewhere.com',
                     'uuid': time.time(),
                     'ip': '127.0.0.1'}

    @mock.patch('urllib2.OpenerDirector.open')
    def test_auth_fails(self, opener):
        opener.return_value = StringIO(auth_error)
        self.assertRaises(paypal.AuthError, paypal.get_paykey, self.data)

    @mock.patch('urllib2.OpenerDirector.open')
    def test_get_key(self, opener):
        opener.return_value = StringIO(good_response)
        eq_(paypal.get_paykey(self.data), 'AP-9GD76073HJ780401K')

    def _test_no_mock(self):
        # Remove _ and run if you'd like to try unmocked.
        return paypal.get_paykey(self.data)


@mock.patch('paypal.urllib.urlopen')
def test_check_paypal_id(urlopen_mock):
    urlopen_mock.return_value = StringIO('ACK=Success')
    val = paypal.check_paypal_id(u'\u30d5\u30a9\u30af\u3059\u3051')
    eq_(val, (True, None))
