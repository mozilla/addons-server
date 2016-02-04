from django.contrib.auth import authenticate

from olympia.amo.tests import TestCase


class TestAmoUserBackend(TestCase):
    fixtures = ['users/test_backends']

    def test_success(self):
        assert authenticate(username='jbalogh@mozilla.com',
                            password='password')

    def test_failure(self):
        assert not authenticate(username='jbalogh@mozilla.com', password='x')
