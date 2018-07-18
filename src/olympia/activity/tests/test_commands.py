from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

from olympia import amo
from olympia.activity.models import ActivityLogToken
from olympia.amo.tests import TestCase, addon_factory, user_factory


class TestRepudiateActivityLogToken(TestCase):
    def setUp(self):
        addon = addon_factory()
        self.version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        self.token1 = ActivityLogToken.objects.create(
            uuid='5a0b8a83d501412589cc5d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        self.token2 = ActivityLogToken.objects.create(
            uuid='8a0b8a834e71412589cc5d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        self.token3 = ActivityLogToken.objects.create(
            uuid='336ae924bc23804cef345d562334b46b',
            version=self.version,
            user=user_factory(),
        )
        addon2 = addon_factory()
        addon2_version = addon2.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        self.token_diff_version = ActivityLogToken.objects.create(
            uuid='470023efdac5730773340eaf3080b589',
            version=addon2_version,
            user=user_factory(),
        )

    def test_with_tokens(self):
        call_command(
            'repudiate_token',
            '5a0b8a83d501412589cc5d562334b46b',
            '8a0b8a834e71412589cc5d562334b46b',
        )
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert not self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()

    def test_with_version(self):
        call_command('repudiate_token', version_id=self.version.id)
        assert self.token1.reload().is_expired()
        assert self.token2.reload().is_expired()
        assert self.token3.reload().is_expired()
        assert not self.token_diff_version.reload().is_expired()

    def test_with_token_and_version_ignores_version(self):
        call_command(
            'repudiate_token',
            '5a0b8a83d501412589cc5d562334b46b',
            version_id=self.version.id,
        )
        assert self.token1.reload().is_expired()  # token supplied is expired.
        assert not self.token2.reload().is_expired()  # version supplied isn't.
        assert not self.token3.reload().is_expired()  # check the others too.
        assert not self.token_diff_version.reload().is_expired()

    def test_no_tokens_no_version_is_error(self):
        with pytest.raises(CommandError):
            call_command('repudiate_token')
