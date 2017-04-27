# -*- coding: utf-8 -*-
from olympia.amo.tests import BaseTestCase, collection_factory
from olympia.bandwagon.serializers import SimpleCollectionSerializer


class TestSimpleCollectionSerializer(BaseTestCase):
    serializer = SimpleCollectionSerializer

    def setUp(self):
        self.collection = collection_factory()

    def serialize(self):
        return self.serializer(self.collection).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.collection.id
        assert data['name'] == {'en-US': self.collection.name}
        assert data['url'] == self.collection.get_abs_url()
        assert data['addon_count'] == self.collection.addon_count
