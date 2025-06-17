import pytest
import requests

from olympia.amo.tests import TestCase


@pytest.mark.allow_external_http_requests
class TestCertifi(TestCase):
    def test_no_certificate_errors_aws(self):
        response = requests.get('https://s3.amazonaws.com/', verify=True)
        response.raise_for_status()

    def test_no_certificate_errors_google(self):
        response = requests.get('https://www.google.com', verify=True)
        response.raise_for_status()
