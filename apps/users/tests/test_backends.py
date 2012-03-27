from django.contrib.auth import authenticate

import amo.tests
from users.models import UserProfile


class TestAmoUserBackend(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def test_success_without_user(self):
        """Make sure a contrib.auth.User gets created when we log in."""
        u = UserProfile.objects.get(email='newuser@example.com')
        assert u.user is None
        assert authenticate(username='newuser@example.com', password='foo')
        u = UserProfile.objects.get(email='newuser@example.com')
        assert u.user is not None
        assert u.user.email == 'newuser@example.com'

    def test_success_with_user(self):
        assert authenticate(username='jbalogh@mozilla.com', password='foo')

    def test_failure_without_user(self):
        """Make sure a user isn't created on a failed password."""
        u = UserProfile.objects.get(email='newuser@example.com')
        assert u.user is None
        assert not authenticate(username='newuser@example.com', password='bar')
        assert u.user is None

    def test_failure_with_user(self):
        assert not authenticate(username='jbalogh@mozilla.com', password='x')
