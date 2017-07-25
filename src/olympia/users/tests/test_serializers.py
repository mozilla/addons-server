from rest_framework.test import APIRequestFactory

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.users.models import UserProfile
from olympia.users.serializers import (
    AddonDeveloperSerializer, BaseUserSerializer)


class TestBaseUserSerializer(TestCase):
    serializer_class = BaseUserSerializer

    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()

    def serialize(self):
        # Manually reload the user first to clear any cached properties.
        self.user = UserProfile.objects.get(pk=self.user.pk)
        serializer = self.serializer_class(context={'request': self.request})
        return serializer.to_representation(self.user)

    def test_basic(self):
        result = self.serialize()
        assert result['id'] == self.user.pk
        assert result['name'] == self.user.name
        assert result['url'] is None

    def test_url_for_yourself(self):
        # should include account profile url
        self.request.user = self.user
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_url_for_developers(self):
        # should include account profile url
        addon_factory(users=[self.user])
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())

    def test_url_for_admins(self):
        # should include account profile url
        admin = user_factory()
        self.grant_permission(admin, 'Users:Edit')
        self.request.user = admin
        result = self.serialize()
        assert result['url'] == absolutify(self.user.get_url_path())


class TestAddonDeveloperSerializer(TestBaseUserSerializer):
    serializer_class = AddonDeveloperSerializer

    def test_picture(self):
        serial = self.serialize()
        assert ('anon_user.png' in serial['picture_url'])

        self.user.update(picture_type='image/jpeg')
        serial = self.serialize()
        assert serial['picture_url'] == absolutify(self.user.picture_url)
        assert '%s.png' % self.user.id in serial['picture_url']
