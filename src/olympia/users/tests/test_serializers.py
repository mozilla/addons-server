from rest_framework.test import APIRequestFactory

from olympia.amo.helpers import absolutify
from olympia.amo.tests import TestCase, user_factory
from olympia.users.models import UserProfile
from olympia.users.serializers import BaseUserSerializer


class TestBaseUserSerializer(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()

    def serialize(self):
        # Manually reload the user first to clear any cached properties.
        self.user = UserProfile.objects.get(pk=self.user.pk)
        serializer = BaseUserSerializer(context={'request': self.request})
        return serializer.to_representation(self.user)

    def test_basic(self):
        result = self.serialize()
        assert result['name'] == self.user.name
        assert result['url'] == absolutify(self.user.get_url_path())
