import mock

from amo.tests import TestCase
from users.models import UserProfile

from ..models import APIKey, SYMMETRIC_JWT_TYPE
import pytest


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

    def test_generate_new_unique_keys(self):
        last_key = None
        for counter in range(3):
            credentials = APIKey.new_jwt_credentials(self.user)
            assert credentials.key != last_key
            last_key = credentials.key

    def test_too_many_tries_at_finding_a_unique_key(self):
        max = 3

        # Make APIKey.objects.filter().exists() always return True.
        patch = mock.patch('apps.api.models.APIKey.objects.filter')
        mock_filter = patch.start()
        self.addCleanup(patch.stop)
        mock_filter.return_value.exists.return_value = True

        with pytest.raises(RuntimeError):
            for counter in range(max + 1):
                APIKey.get_unique_key('key-prefix-', max_tries=max)

    def test_generate_secret(self):
        assert APIKey.generate_secret(32)  # check for exceptions

    def test_generated_secret_must_be_long_enough(self):
        with pytest.raises(ValueError):
            APIKey.generate_secret(31)

    def test_hide_inactive_jwt_keys(self):
        active_key = APIKey.new_jwt_credentials(self.user)
        inactive_key = APIKey.new_jwt_credentials(self.user)
        inactive_key.update(is_active=False)
        fetched_key = APIKey.get_jwt_key(user=self.user)
        assert fetched_key == active_key
