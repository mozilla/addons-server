from nose.tools import eq_

import amo.tests
from mkt.collections.models import Collection
from mkt.collections.serializers import (CollectionMembershipField,
                                         CollectionSerializer,)
from mkt.webapps.utils import app_to_dict


class CollectionDataMixin(object):
    collection_data = {
        'collection_type': 0,
        'name': 'My Favorite Games',
        'description': 'A collection of my favorite games',
    }


class TestCollectionMembershipField(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        self.app = amo.tests.app_factory()
        self.collection.add_app(self.app)
        self.field = CollectionMembershipField()

    def test_to_native(self):
        membership = self.collection.collectionmembership_set.all()[0]
        native = self.field.to_native(membership)
        eq_(native, app_to_dict(self.app))


class TestCollectionSerializer(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        self.serializer = CollectionSerializer()

    def test_to_native(self, apps=None):
        if apps:
            for app in apps:
                self.collection.add_app(app)
        else:
            apps = []

        data = self.serializer.to_native(self.collection)
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], data[name])
        self.assertSetEqual(data.keys(), ['id', 'name', 'description', 'apps',
                                          'collection_type', 'category',
                                          'region', 'carrier', 'author'])
        for order, app in enumerate(apps):
            eq_(data['apps'][order]['slug'], app.app_slug)

    def test_to_native_with_apps(self):
        apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.test_to_native(apps=apps)
