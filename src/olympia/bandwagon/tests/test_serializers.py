# -*- coding: utf-8 -*-
from django.conf import settings

from olympia.amo.tests import (
    BaseTestCase, addon_factory, collection_factory, user_factory)
from olympia.bandwagon.models import CollectionAddon
from olympia.bandwagon.serializers import (
    CollectionAddonSerializer, CollectionSerializer,
    CollectionWithAddonsSerializer)


class TestCollectionSerializer(BaseTestCase):
    serializer = CollectionSerializer

    def setUp(self):
        super(TestCollectionSerializer, self).setUp()
        self.user = user_factory()
        self.collection = collection_factory()
        self.collection.update(author=self.user)

    def serialize(self):
        return self.serializer(self.collection).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.collection.id
        assert data['uuid'] == self.collection.uuid
        assert data['name'] == {'en-US': self.collection.name}
        assert data['description'] == {'en-US': self.collection.description}
        assert data['url'] == self.collection.get_abs_url()
        assert data['addon_count'] == self.collection.addon_count
        assert data['modified'] == (
            self.collection.modified.replace(microsecond=0).isoformat() + 'Z')
        assert data['author']['id'] == self.user.id
        assert data['slug'] == self.collection.slug
        assert data['public'] == self.collection.listed
        assert data['default_locale'] == self.collection.default_locale


class TestCollectionAddonSerializer(BaseTestCase):

    def setUp(self):
        self.collection = collection_factory()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.item = CollectionAddon.objects.get(addon=self.addon,
                                                collection=self.collection)
        self.item.comments = u'Dis is nice'
        self.item.save()

    def serialize(self):
        return CollectionAddonSerializer(self.item).data

    def test_basic(self):
        data = self.serialize()
        assert data['addon']['id'] == self.collection.addons.all()[0].id
        assert data['downloads'] == self.item.downloads
        assert data['notes'] == {'en-US': self.item.comments}


class TestCollectionWithAddonsSerializer(TestCollectionSerializer):
    serializer = CollectionWithAddonsSerializer

    def setUp(self):
        super(TestCollectionWithAddonsSerializer, self).setUp()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)

    def test_basic(self):
        super(TestCollectionWithAddonsSerializer, self).test_basic()
        data = self.serialize()
        collection_addon = CollectionAddon.objects.get(
            addon=self.addon, collection=self.collection)
        assert data['addons'] == [
            CollectionAddonSerializer(collection_addon).data
        ]
        assert data['addons'][0]['addon']['id'] == self.addon.id

    def test_page_size(self):
        # Add 3 more addons to the collection.
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        data = self.serialize()
        assert len(data['addons']) == 4
        settings.REST_FRAMEWORK['PAGE_SIZE'] = 3
        data = self.serialize()
        assert len(data['addons']) == 3
