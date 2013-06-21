from datetime import datetime

from addons.models import Addon
from amo.tests import TestCase
from comm.models import CommunicationThread, CommunicationThreadToken
from mkt.constants import comm as const
from users.models import UserProfile


class TestThreadTokenModel(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def setUp(self):
        addon = Addon.objects.get(pk=3615)
        self.thread = CommunicationThread(addon=addon)
        user = UserProfile.objects.all()[0]
        self.token = CommunicationThreadToken(thread=self.thread, user=user)
        self.token.modified = datetime.now()
        self.token.use_count = 0

    def test_live_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token is fresh (not expired).
        """
        assert self.token.is_valid()

    def test_expired_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token has expired.
        """
        self.token.modified = self.days_ago(const.THREAD_TOKEN_EXPIRY + 1)
        assert not self.token.is_valid()

    def test_unused_token_is_valid(self):
        """
        Test `is_valid()` when the token is unused.
        """
        assert self.token.is_valid()

    def test_max_used_thread_token_is_valid(self):
        """
        Test `is_valid()` when the token has been fully used.
        """
        self.token.use_count = const.MAX_TOKEN_USE_COUNT
        assert not self.token.is_valid()

    def test_reset_uuid(self):
        """
        Test `reset_uuid()` generates a differ uuid.
        """
        self.thread.save()
        self.token.thread = self.thread
        self.token.save()
        uuid = self.token.uuid
        assert uuid

        self.token.reset_uuid()
        assert self.token.uuid
        assert uuid != self.token.uuid
