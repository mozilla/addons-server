from olympia.amo.tests import TestCase
from olympia.users.backends import AmoUserBackend, TestUserBackend
from olympia.users.models import UserProfile


class TestAmoUserBackend(TestCase):
    fixtures = ['users/test_backends']

    def test_success(self):
        assert AmoUserBackend().authenticate(
            username='jbalogh@mozilla.com', password='password')

    def test_failure(self):
        assert not AmoUserBackend().authenticate(
            username='jbalogh@mozilla.com', password='x')


class TestTestUserBackend(TestCase):

    def test_login_with_email(self):
        user = UserProfile.objects.create(
            email='me@mozilla.com', username='whatever', password='pass')
        assert TestUserBackend().authenticate(email='me@mozilla.com') == user

    def test_login_with_username(self):
        user = UserProfile.objects.create(
            email='me@mozilla.com', username='whatever', password='pass')
        assert TestUserBackend().authenticate(username='whatever') == user

    def test_no_user(self):
        assert TestUserBackend().authenticate(username='hmm') is None
