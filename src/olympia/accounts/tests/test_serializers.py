from olympia.amo.tests import BaseTestCase
from olympia.accounts.serializers import UserProfileSerializer
from olympia.users.models import UserProfile


class TestAccountSerializer(BaseTestCase):

    def setUp(self):
        self.user = UserProfile.objects.create(email='a@m.o')

    def test_picture_url(self):
        serial = UserProfileSerializer(instance=self.user)
        assert ('anon_user.png' in serial.data['picture_url'])
