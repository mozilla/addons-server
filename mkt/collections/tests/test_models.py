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

        eq_(list(self.collection.apps()), [self.apps[2], self.apps[1]])

    def test_apps(self):
        self._generate_apps()

        # First fetch the apps. Depending CACHE_EMPTY_QUERYSETS an empty list
        # will be cached, or not.
        self.assertSetEqual(self.collection.apps(), [])
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [])

        # Add an app and re-check the apps list. Regardless of whether caching
        # took place in the previous step, we should get a new, up to date apps
        # list.
        self.collection.add_app(self.apps[0])
        self.assertSetEqual(self.collection.apps(), [self.apps[0]])
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [0])

        # Add an app again. This time we know for sure caching took place in
        # the previous step, and we still want to get the new, up to date apps
        # list.
        self.collection.add_app(self.apps[1])
        self.assertSetEqual(self.collection.apps(),
                            [self.apps[0], self.apps[1]])
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [0, 1])

        # Add and test the rest of the apps in one go.
        self.collection.add_app(self.apps[2])
        self.collection.add_app(self.apps[3])
        self.assertSetEqual(self.collection.apps(), self.apps)
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [0, 1, 2, 3])

    def test_remove_apps(self):
        self._generate_apps()
        self._add_apps()
        self.assertSetEqual(self.collection.apps(), self.apps)
        self.collection.remove_app(self.apps[0])
        self.assertSetEqual(self.collection.apps(),
                            [self.apps[1], self.apps[2], self.apps[3]])
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [1, 2, 3])
        self.collection.remove_app(self.apps[2])
        self.assertSetEqual(self.collection.apps(),
                            [self.apps[1], self.apps[3]])
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [1, 3])

    def test_app_deleted(self):
        collection = self.collection
        app = amo.tests.app_factory()
        collection.add_app(app)
        self.assertSetEqual(collection.apps(), [app])
        self.assertSetEqual(collection.collectionmembership_set.all(),
            [CollectionMembership.objects.get(collection=collection, app=app)])

        app.delete()

        self.assertSetEqual(collection.apps(), [])
        self.assertSetEqual(collection.collectionmembership_set.all(), [])

    def test_app_disabled_by_user(self):
        collection = self.collection
        app = amo.tests.app_factory()
        collection.add_app(app)
        self.assertSetEqual(collection.apps(), [app])
        self.assertSetEqual(collection.collectionmembership_set.all(),
            [CollectionMembership.objects.get(collection=collection, app=app)])

        app.update(disabled_by_user=True)

        self.assertSetEqual(collection.apps(), [])

        # The collection membership still exists here, the app is not deleted,
        # only disabled.
        self.assertSetEqual(collection.collectionmembership_set.all(),
            [CollectionMembership.objects.get(collection=collection, app=app)])

    def test_app_pending(self):
        collection = self.collection
        app = amo.tests.app_factory()
        collection.add_app(app)
        self.assertSetEqual(collection.apps(), [app])
        self.assertSetEqual(collection.collectionmembership_set.all(),
            [CollectionMembership.objects.get(collection=collection, app=app)])

        app.update(status=amo.STATUS_PENDING)

        self.assertSetEqual(collection.apps(), [])

        # The collection membership still exists here, the app is not deleted,
        # just not public.
        self.assertSetEqual(collection.collectionmembership_set.all(),
            [CollectionMembership.objects.get(collection=collection, app=app)])

    def test_mixed_ordering(self):
        self._generate_apps()

        extra_app = amo.tests.app_factory()
        added = self.collection.add_app(extra_app, order=3)
        eq_(added.order, 3)
        self.assertSetEqual(self.collection.apps(), [extra_app])
        self._add_apps()
        eq_(list(CollectionMembership.objects.values_list('order', flat=True)),
            [3, 4, 5, 6, 7])
