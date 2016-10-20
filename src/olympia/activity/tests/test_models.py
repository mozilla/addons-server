from olympia import amo
from olympia.activity.models import ActivityLogToken, MAX_TOKEN_USE_COUNT
from olympia.amo.tests import (
    addon_factory, user_factory, TestCase, version_factory)


class TestActivityLogToken(TestCase):
    def setUp(self):
        super(TestActivityLogToken, self).setUp()
        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        self.version.update(created=self.days_ago(1))
        self.user = user_factory()
        self.token = ActivityLogToken.objects.create(
            version=self.version, user=self.user)

    def test_validity_use_expiry(self):
        assert self.token.use_count == 0
        self.token.increment_use()
        assert self.token.use_count == 1
        assert not self.token.is_expired()
        self.token.expire()
        assert self.token.use_count == MAX_TOKEN_USE_COUNT
        # Being expired is invalid too.
        assert self.token.is_expired()
        # But the version is still the latest version.
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert not self.token.is_valid()

    def test_increment_use(self):
        assert self.token.use_count == 0
        self.token.increment_use()
        assert self.token.use_count == 1
        token_from_db = ActivityLogToken.objects.get(
            version=self.version, user=self.user)
        assert token_from_db.use_count == 1

    def test_validity_version_out_of_date(self):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        # The token isn't expired.
        assert not self.token.is_expired()
        # But is invalid, because the version isn't the latest version.
        assert not self.token.is_valid()

    def test_validity_still_valid_if_new_version_in_different_channel(self):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)

        # The token isn't expired.
        assert not self.token.is_expired()
        # It's also still valid, since our version is still the latest listed
        # one.
        assert self.token.is_valid()
