from django.core.urlresolvers import reverse

from nose.tools import eq_

import amo.tests

from mkt.collections.models import Collection, CollectionMembership


class TestCollection(amo.tests.TestCase):

    def setUp(self):
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.collection_data = {
            'name': 'My Favorite Games',
            'description': 'A collection of my favorite games',
            'collection_type': 1
        }
        self.collection = Collection.objects.create(**self.collection_data)

    def test_collection(self):
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], getattr(self.collection, name))

    def test_add_app_order_override(self):
        added = self.collection.add_app(self.apps[1], order=3)
        eq_(added.order, 3)
        eq_(added.app, self.apps[1])
        eq_(added.collection, self.collection)

        added = self.collection.add_app(self.apps[2], order=1)
        eq_(added.order, 1)
        eq_(added.app, self.apps[2])
        eq_(added.collection, self.collection)

        eq_(self.collection.apps(), [self.apps[2], self.apps[1]])

    def add_apps(self):
        for app in self.apps:
            self.collection.add_app(app)

    def test_apps(self):
        self.assertSetEqual(self.collection.apps(), [])
        self.add_apps()
        self.assertSetEqual(self.collection.apps(), self.apps)
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [1, 2, 3, 4])

    def test_mixed_ordering(self):
        extra_app = amo.tests.app_factory()
        added = self.collection.add_app(extra_app, order=3)
        eq_(added.order, 3)
        self.assertSetEqual(self.collection.apps(), [extra_app])
        self.add_apps()
        all_apps = self.collection.apps()
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [3, 4, 5, 6, 7])

    def test_app_urls(self):
        self.assertSetEqual(self.collection.app_urls(), [])
        self.add_apps()
        app_urls = [reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': a.pk
        }) for a in self.apps]
        self.assertSetEqual(self.collection.app_urls(), app_urls)
