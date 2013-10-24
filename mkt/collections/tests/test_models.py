from nose.tools import eq_

import amo.tests
from mkt.collections.constants import COLLECTIONS_TYPE_FEATURED
from mkt.collections.models import Collection, CollectionMembership


class TestCollection(amo.tests.TestCase):

    def setUp(self):
        self.collection_data = {
            'background_color': '#FF00FF',
            'collection_type': COLLECTIONS_TYPE_FEATURED,
            'description': 'A collection of my favourite games',
            'name': 'My Favourite Games',
            'slug': 'my-favourite-games',
            'text_color': '#00FF00',
        }
        self.collection = Collection.objects.create(**self.collection_data)

    def test_save(self):
        self.collection = Collection.objects.all()[0]
        self.collection.save()

    def _add_apps(self):
        for app in self.apps:
            self.collection.add_app(app)

    def _generate_apps(self):
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]

    def test_collection(self):
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], getattr(self.collection, name))

    def test_collection_no_colors(self):
        self.collection_data.pop('background_color')
        self.collection_data.pop('text_color')
        self.collection_data['slug'] = 'favorite-games-2'
        self.collection = Collection.objects.create(**self.collection_data)
        self.test_collection()

    def test_add_app_order_override(self):
        self._generate_apps()

        added = self.collection.add_app(self.apps[1], order=3)
        eq_(added.order, 3)
        eq_(added.app, self.apps[1])
        eq_(added.collection, self.collection)

        added = self.collection.add_app(self.apps[2], order=1)
        eq_(added.order, 1)
        eq_(added.app, self.apps[2])
        eq_(added.collection, self.collection)

        eq_(self.collection.apps.all(), [self.apps[2], self.apps[1]])

    def test_apps(self):
        self._generate_apps()

        self.assertSetEqual(self.collection.apps.all(), [])
        self._add_apps()
        self.assertSetEqual(self.collection.apps.all(), self.apps)
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [0, 1, 2, 3])

    def test_mixed_ordering(self):
        self._generate_apps()

        extra_app = amo.tests.app_factory()
        added = self.collection.add_app(extra_app, order=3)
        eq_(added.order, 3)
        self.assertSetEqual(self.collection.apps.all(), [extra_app])
        self._add_apps()
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [3, 4, 5, 6, 7])
