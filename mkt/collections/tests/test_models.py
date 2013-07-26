from django.core.urlresolvers import reverse
from django.db.models import Max

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

    def test_add_app(self, app=None, order=None):
        if not app:
            app = self.apps[0]
        added = self.collection.add_app(app, order=order)
        if not order:
            aggregate = CollectionMembership.objects.aggregate(Max('order'))
            eq_(added.order, aggregate['order__max'])
        else:
            eq_(added.order, order)
        eq_(added.app, app)
        eq_(added.collection, self.collection)

    def test_add_app_order_override(self):
        self.test_add_app(app=self.apps[1], order=3)
        self.test_add_app(app=self.apps[2], order=1)
        eq_(self.collection.apps(), [self.apps[2], self.apps[1]])

    def add_apps(self):
        for n, app in enumerate(self.apps):
            self.collection.add_app(app, order=n)

    def test_apps(self):
        self.assertSetEqual(self.collection.apps(), [])
        self.add_apps()
        self.assertSetEqual(self.collection.apps(), self.apps)

    def test_app_urls(self):
        self.assertSetEqual(self.collection.app_urls(), [])
        self.add_apps()
        app_urls = [reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': a.pk
        }) for a in self.apps]
        self.assertSetEqual(self.collection.app_urls(), app_urls)
