from django.contrib.auth import authenticate

import amo.tests


class TestAmoUserBackend(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def test_success(self):
        assert authenticate(username='jbalogh@mozilla.com',
                            password='password')

    def test_failure(self):
        assert not authenticate(username='jbalogh@mozilla.com', password='x')
