from cStringIO import StringIO

import mock
from nose.tools import eq_

import paypal


@mock.patch('paypal.urllib.urlopen')
def test_check_paypal_id(urlopen_mock):
    urlopen_mock.return_value = StringIO('ACK=Success')
    val = paypal.check_paypal_id(u'\u30d5\u30a9\u30af\u3059\u3051')
    eq_(val, (True, None))
