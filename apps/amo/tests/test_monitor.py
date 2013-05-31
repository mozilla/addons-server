import time

from django.conf import settings

from mock import patch
from nose.tools import eq_
import requests

import amo.tests
from amo.monitors import receipt_signer as signer, package_signer

@patch.object(settings, 'SIGNED_APPS_SERVER_ACTIVE', True)
@patch.object(settings, 'SIGNING_SERVER', 'http://foo/')
@patch.object(settings, 'SIGNED_APPS_SERVER', 'http://baz/')
class TestMonitor(amo.tests.TestCase):
    # Some rudimentary tests for the rest of the monitor would be nice.

    def _make_receipt(self):
        now = time.time()
        return [
            {'exp': now + (3600 * 36), 'iss': 'http://foo/cert.jwk'}, '']

    @patch('amo.monitors.receipt')
    def test_sign_fails(self, receipt):
        from lib.crypto.receipt import SigningError
        receipt.sign.side_effect = SigningError
        eq_(signer()[0][:16], 'Error on signing')

    @patch('amo.monitors.receipt')
    def test_crack_fails(self, receipt):
        receipt.crack.side_effect = ValueError
        eq_(signer()[0][:25], 'Error on cracking receipt')

    @patch('amo.monitors.receipt')
    def test_expire(self, receipt):
        now = time.time()
        receipt.crack.return_value = [{'exp': now + (3600 * 12)}, '']
        eq_(signer()[0][:21], 'Cert will expire soon')

    @patch('requests.get')
    @patch('amo.monitors.receipt')
    def test_good(self, receipt, cert_response):
        receipt.crack.return_value = self._make_receipt()
        cert_response.return_value.ok = True
        cert_response.return_value.json = lambda: {'jwk': []}
        eq_(signer()[0], '')

    @patch('requests.get')
    @patch('amo.monitors.receipt')
    def test_public_cert_connection_error(self, receipt, cert_response):
        receipt.crack.return_value = self._make_receipt()
        cert_response.side_effect = Exception
        eq_(signer()[0][:29], 'Error on checking public cert')

    @patch('requests.get')
    @patch('amo.monitors.receipt')
    def test_public_cert_not_found(self, receipt, cert_response):
        receipt.crack.return_value = self._make_receipt()
        cert_response.return_value.ok = False
        cert_response.return_value.reason = 'Not Found'
        eq_(signer()[0][:29], 'Error on checking public cert')

    @patch('requests.get')
    @patch('amo.monitors.receipt')
    def test_public_cert_no_json(self, receipt, cert_response):
        receipt.crack.return_value = self._make_receipt()
        cert_response.return_value.ok = True
        cert_response.return_value.json = lambda: None
        eq_(signer()[0][:29], 'Error on checking public cert')

    @patch('requests.get')
    @patch('amo.monitors.receipt')
    def test_public_cert_invalid_jwk(self, receipt, cert_response):
        receipt.crack.return_value = self._make_receipt()
        cert_response.return_value.ok = True
        cert_response.return_value.json = lambda: {'foo': 1}
        eq_(signer()[0][:29], 'Error on checking public cert')


    @patch('requests.post')
    def test_app_sign_good(self, sign_response):
        sign_response().status_code = 200
        sign_response().content = '{"zigbert.rsa": "Vm0wd2QyUXlVWGxW"}'
        eq_(package_signer()[0], '')


    @patch('requests.post')
    def test_app_sign_fail(self, sign_response):
        sign_response().side_effect = requests.exceptions.HTTPError
        assert package_signer()[0].startswith('Error on package signing')
