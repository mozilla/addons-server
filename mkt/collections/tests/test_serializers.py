from django.core.urlresolvers import reverse

from nose.tools import eq_

import amo.tests
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer


class TestCollectionSerializer(amo.tests.TestCase):

    def setUp(self):
        self.collection_data = {
            'name': 'My Favorite Games',
            'description': 'A collection of my favorite games'
        }
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

        app_urls = [reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': a.pk
        }) for a in apps]
        self.assertSetEqual(data['apps'], app_urls)
        self.assertSetEqual(data.keys(), ['id', 'name', 'description', 'apps'])

    def test_to_native_with_apps(self):
        apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.test_to_native(apps=apps)
