from amo.tests import TestCase
from users.models import UserProfile

from ..models import APIKey, SYMMETRIC_JWT_TYPE


class TestAPIKey(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestAPIKey, self).setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_new_jwt_credentials(self):
        credentials = APIKey.new_jwt_credentials(self.user)
        assert credentials.user == self.user
        assert credentials.type == SYMMETRIC_JWT_TYPE
        assert credentials.key
        assert credentials.secret

    def test_generate_secret(self):
        assert APIKey.generate_secret(32)  # check for exceptions

    def test_generated_secret_must_be_long_enough(self):
        with self.assertRaises(ValueError):
            APIKey.generate_secret(31)
