from unittest import mock

from django.core import mail
from django.db import IntegrityError

from olympia.amo.tests import TestCase
from olympia.users.models import UserProfile

from ..models import SYMMETRIC_JWT_TYPE, APIKey, APIKeyConfirmation


class TestAPIKey(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestAPIKey, self).setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_new_jwt_credentials(self):
        credentials = APIKey.new_jwt_credentials(self.user)
        assert credentials.user == self.user
        assert credentials.type == SYMMETRIC_JWT_TYPE
        assert credentials.key
        assert credentials.secret
        assert credentials.is_active

    def test_string_representation(self):
        credentials = APIKey.new_jwt_credentials(self.user)
        str_creds = str(credentials)
        assert credentials.key in str_creds
        assert credentials.secret not in str_creds
        assert str(credentials.user) in str_creds

    def test_cant_have_two_active_keys_for_same_user(self):
        APIKey.new_jwt_credentials(self.user)
        with self.assertRaises(IntegrityError):
            APIKey.new_jwt_credentials(self.user)

    def test_generate_new_unique_keys(self):
        last_key = None
        for counter in range(3):
            credentials = APIKey.new_jwt_credentials(self.user)
            assert credentials.key != last_key
            last_key = credentials.key
            # Deactivate last key so that we can create a new one without
            # triggering an IntegrityError.
            credentials.update(is_active=None)

    def test_too_many_tries_at_finding_a_unique_key(self):
        max = 3

        # Make APIKey.objects.filter().exists() always return True.
        patch = mock.patch('olympia.api.models.APIKey.objects.filter')
        mock_filter = patch.start()
        self.addCleanup(patch.stop)
        mock_filter.return_value.exists.return_value = True

        with self.assertRaises(RuntimeError):
            for counter in range(max + 1):
                APIKey.get_unique_key('key-prefix-', max_tries=max)

    def test_generate_secret(self):
        assert APIKey.generate_secret(32)  # check for exceptions

    def test_generated_secret_must_be_long_enough(self):
        with self.assertRaises(ValueError):
            APIKey.generate_secret(31)

    def test_hide_inactive_jwt_keys(self):
        inactive_key = APIKey.new_jwt_credentials(self.user)
        inactive_key.update(is_active=None)
        # Make a new active key, but that is somehow older than the inactive
        # one: it should still be the one returned by get_jwt_key(), since it's
        # the only active one.
        active_key = APIKey.new_jwt_credentials(self.user)
        active_key.update(created=self.days_ago(1))
        fetched_key = APIKey.get_jwt_key(user=self.user)
        assert fetched_key == active_key


class TestAPIKeyConfirmation(TestCase):
    def test_generate_token(self):
        token = APIKeyConfirmation.generate_token()
        assert len(token) == 20
        assert token != APIKeyConfirmation.generate_token()
        assert token != APIKeyConfirmation.generate_token()

    def test_is_token_valid(self):
        confirmation = APIKeyConfirmation()
        confirmation.token = APIKeyConfirmation.generate_token()
        assert confirmation.is_token_valid(confirmation.token)
        assert not confirmation.is_token_valid(confirmation.token[:19])
        assert not confirmation.is_token_valid(confirmation.token[1:])
        assert not confirmation.is_token_valid('a' * 20)

    def test_send_confirmation_email(self):
        token = 'abcdefghijklmnopqrst'
        confirmation = APIKeyConfirmation()
        confirmation.token = token
        confirmation.user = UserProfile(email='foo@bar.com', display_name='Fô')
        assert len(mail.outbox) == 0
        confirmation.send_confirmation_email()
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        expected_url = (
            f'http://testserver/en-US/developers/addon/api/key/?token={token}'
        )
        assert message.to == ['foo@bar.com']
        assert message.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'
        assert message.subject == 'Confirmation for developer API keys'
        assert expected_url in message.body
