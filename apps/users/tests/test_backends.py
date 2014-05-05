from django.contrib.auth import authenticate

import amo.tests
from users.models import UserProfile


class TestAmoUserBackend(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def test_success(self):
        assert authenticate(username='jbalogh@mozilla.com', password='foo')

    def test_failure(self):
        assert not authenticate(username='jbalogh@mozilla.com', password='x')
