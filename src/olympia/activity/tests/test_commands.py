from django.core.management import call_command

from olympia.activity.models import ActivityLogToken
from olympia.amo.tests import addon_factory, user_factory, TestCase


class TestActivityLogToken(TestCase):
    def setUp(self):
        self.version = addon_factory().latest_version
        self.token1 = ActivityLogToken.objects.create(
            uuid='5a0b8a83d501412589cc5d562334b46b',
            version=self.version, user=user_factory())
        self.token2 = ActivityLogToken.objects.create(
            uuid='8a0b8a834e71412589cc5d562334b46b',
            version=self.version, user=user_factory())
        self.token3 = ActivityLogToken.objects.create(
            uuid='336ae924bc23804cef345d562334b46b',
            version=self.version, user=user_factory())
        self.token_diff_version = ActivityLogToken.objects.create(
            uuid='470023efdac5730773340eaf3080b589',
            version=addon_factory().latest_version, user=user_factory())

    def test_repudiate_token_with_tokens(self):
        call_command('repudiate_token',
                     '5a0b8a83d501412589cc5d562334b46b',
                     '8a0b8a834e71412589cc5d562334b46b')
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert not self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()

    def test_repudiate_token_with_version(self):
        call_command('repudiate_token', version_id=self.version.id)
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()
