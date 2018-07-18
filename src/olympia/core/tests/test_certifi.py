# -*- coding: utf-8 -*-
import pytest
import requests

from cryptography.hazmat.backends.openssl.backend import backend

from olympia.amo.tests import TestCase


@pytest.mark.withoutresponses
class TestCertifi(TestCase):
    def test_openssl_version(self):
        # At the time of writing cryptography is statically compiled
        # against OpenSSL 1.1.0f  25 May 2017 (27-09-2017)
        # And we need anything more recent than 1.0.1
        assert backend._lib.CRYPTOGRAPHY_OPENSSL_110_OR_GREATER

    def test_no_certificate_errors_aws(self):
        resp = requests.get('https://s3.amazonaws.com/', verify=True)
        assert resp.status_code == 200

    def test_no_certificate_errors_google(self):
        resp = requests.get('https://www.google.com', verify=True)
        assert resp.status_code == 200
