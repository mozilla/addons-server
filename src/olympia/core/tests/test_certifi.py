# -*- coding: utf-8 -*-
import pytest
import requests

from olympia.amo.tests import TestCase


@pytest.mark.allow_external_http_requests
class TestCertifi(TestCase):
    def test_no_certificate_errors_aws(self):
        resp = requests.get('https://s3.amazonaws.com/', verify=True)
        assert resp.status_code == 200

    def test_no_certificate_errors_google(self):
        resp = requests.get('https://www.google.com', verify=True)
        assert resp.status_code == 200
