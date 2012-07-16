import time

from django.conf import settings

from mock import patch
from nose.tools import eq_

import amo.tests
from amo.monitors import signer


@patch.object(settings, 'SIGNING_SERVER', 'http://foo/')
class TestMonitor(amo.tests.TestCase):
    # Some rudimentary tests for the rest of the monitor would be nice.

    @patch('amo.monitors.receipt')
    def test_sign_fails(self, receipt):
        receipt.sign.side_effect = receipt.SigningError
        eq_(signer()[0], False)

    @patch('amo.monitors.receipt')
    def test_crack_fails(self, receipt):
        receipt.crack.side_effect = ValueError
        eq_(signer()[0], False)

    @patch('amo.monitors.receipt')
    def test_expire(self, receipt):
        now = time.time()
        receipt.crack.return_value = [{'exp': now + (60 * 60 * 12)}, '']
        eq_(signer()[0], False)

    @patch('amo.monitors.receipt')
    def test_good(self, receipt):
        now = time.time()
        receipt.crack.return_value = [{'exp': now + (60 * 60 * 36)}, '']
        eq_(signer()[0], True)
