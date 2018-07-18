from olympia.amo.tests import TestCase
from olympia.users.backends import TestUserBackend
from olympia.users.models import UserProfile


class TestTestUserBackend(TestCase):
    def test_login_with_email(self):
        user = UserProfile.objects.create(
            email='me@mozilla.com', username='whatever'
        )
        assert TestUserBackend().authenticate(email='me@mozilla.com') == user

    def test_login_with_username(self):
        user = UserProfile.objects.create(
            email='me@mozilla.com', username='whatever'
        )
        assert TestUserBackend().authenticate(username='whatever') == user

    def test_no_user(self):
        assert TestUserBackend().authenticate(username='hmm') is None
