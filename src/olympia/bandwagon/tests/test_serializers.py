from unittest import mock

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.bandwagon.models import CollectionAddon
from olympia.bandwagon.serializers import (
    CollectionAddonSerializer,
    CollectionSerializer,
    CollectionWithAddonsSerializer,
)


class TestCollectionSerializer(TestCase):
    serializer = CollectionSerializer

    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.collection = collection_factory()
        self.collection.update(author=self.user)

    def serialize(self):
        return self.serializer(self.collection).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.collection.id
        assert data['uuid'] == self.collection.uuid.hex
        assert data['name'] == {'en-US': self.collection.name}
        assert data['description'] == {'en-US': self.collection.description}
        assert data['url'] == absolutify(self.collection.get_url_path())
        assert data['addon_count'] == self.collection.addon_count
        assert data['modified'] == (
            self.collection.modified.replace(microsecond=0).isoformat() + 'Z'
        )
        assert data['author']['id'] == self.user.id
        assert data['slug'] == self.collection.slug
        assert data['public'] == self.collection.listed
        assert data['default_locale'] == self.collection.default_locale


class TestCollectionAddonSerializer(TestCase):
    def setUp(self):
        self.collection = collection_factory()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.item = CollectionAddon.objects.get(
            addon=self.addon, collection=self.collection
        )
        self.item.comments = 'Dis is nice'
        self.item.save()

    def serialize(self):
        return CollectionAddonSerializer(self.item).data

    def test_basic(self):
        data = self.serialize()
        assert data['addon']['id'] == self.collection.addons.all()[0].id
        assert data['notes'] == {'en-US': self.item.comments}


class TestCollectionWithAddonsSerializer(TestCollectionSerializer):
    serializer = CollectionWithAddonsSerializer

    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)

    def serialize(self):
        mock_viewset = mock.MagicMock()
        collection_addons = CollectionAddon.objects.filter(
            addon=self.addon, collection=self.collection
        )
        mock_viewset.get_addons_queryset.return_value = collection_addons
        return self.serializer(self.collection, context={'view': mock_viewset}).data

    def test_basic(self):
        super().test_basic()
        collection_addon = CollectionAddon.objects.get(
            addon=self.addon, collection=self.collection
        )
        data = self.serialize()
        assert data['addons'] == [CollectionAddonSerializer(collection_addon).data]
        assert data['addons'][0]['addon']['id'] == self.addon.id
