from olympia.amo.tests import TestCase
from olympia.users.backends import TestUserBackend
from olympia.users.models import UserProfile


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

    def test_login_with_password(self):
        UserProfile.objects.create(
            email='me@mozilla.com', username='whatever', password='pass')
        with self.assertRaises(TypeError):
            TestUserBackend().authenticate(
                email='me@mozilla.com', password='pass')

    def test_client_login_does_not_work_with_password(self):
        UserProfile.objects.create(
            email='me@mozilla.com', username='whatever', password='pass')
        with self.assertRaises(TypeError):
            self.client.login(email='me@mozilla.com', password='pass')
