# -*- coding: utf-8 -*-
import json
from random import shuffle

from django.core.urlresolvers import reverse

from nose import SkipTest
from nose.tools import eq_
from rest_framework.exceptions import PermissionDenied

import amo
import amo.tests
import mkt
from addons.models import Category
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.collections.views import CollectionViewSet
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestCollectionViewSet(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionViewSet, self).setUp()
        self.serializer = CollectionSerializer()
        self.collection_data = {
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'description': u'A cöllection of my favorite games',
            'name': u'My Favorite Gamés',
            'author': u'My Àuthør',
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.list_url = reverse('collections-list')

    def collection_url(self, action, pk):
        return reverse('collections-%s' % action, kwargs={'pk': pk})

    def make_publisher(self):
        self.grant_permission(self.profile, 'Apps:Publisher')

    def add_all_apps(self):
        for app in self.apps:
            self.add_app(self.client, app_id=app.pk)

    def listing(self, client):
        for app in self.apps:
            self.collection.add_app(app)
        res = client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        collection = data['objects'][0]
        apps = collection['apps']

        # Verify that the apps are present in the correct order.
        for order, app in enumerate(self.apps):
            eq_(apps[order]['slug'], app.app_slug)

        # Verify that the collection metadata is in tact.
        for field, value in self.collection_data.iteritems():
            eq_(collection[field], self.collection_data[field])

    def create_additional_data(self):
        self.category = Category.objects.create(slug='Cat',
                                                type=amo.ADDON_WEBAPP)
        self.empty_category = Category.objects.create(slug='Empty Cat',
                                                      type=amo.ADDON_WEBAPP)
        eq_(Category.objects.count(), 2)

        collection_data = {
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'description': 'A collection of my favorite spanish games',
            'name': 'My Favorite spanish games',
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.UNKNOWN_CARRIER.id,
        }
        self.collection2 = Collection.objects.create(**collection_data)

        collection_data = {
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'description': 'A collection of my favorite phone games',
            'name': 'My Favorite phone games',
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.TELEFONICA.id,
        }
        self.collection3 = Collection.objects.create(**collection_data)

        collection_data = {
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'description': 'A collection of my favorite categorized games',
            'name': 'My Favorite categorized games',
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.TELEFONICA.id,
            'category': self.category
        }
        self.collection4 = Collection.objects.create(**collection_data)

    def test_listing(self):
        self.listing(self.anon)

    def test_listing_no_perms(self):
        self.listing(self.client)

    def test_listing_has_perms(self):
        self.make_publisher()
        self.listing(self.client)

    def test_listing_no_filtering(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 4)

    def test_listing_filtering_region(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'region': mkt.regions.SPAIN.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        eq_(collections[2]['id'], self.collection2.id)

    def test_listing_filtering_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, 
            {'carrier': mkt.carriers.TELEFONICA.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)

    def test_listing_filtering_carrier_0(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering on carrier with value 0 (which is valid, and different
        # from the default, which is null). There used to be a bug with falsy
        # values in django-filter 0.6, make sure it doesn't come back.
        res = self.client.get(self.list_url, {'carrier': 0})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection2.id)

    def test_listing_filtering_category(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'category': self.category.pk})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.id)

    def test_listing_filtering_category_region_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {
            'category': self.category.pk,
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.SPRINT.id
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.id)

    def test_listing_filterig_category_region_carrier_fallback(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering with a non-existant category + region + carrier.
        # It should fall back on region+category filtering only, not find
        # anything either, then fall back to category only, then remove
        # all filters because of the order in which filters are dropped.
        res = self.client.get(self.list_url, {
            'category': self.empty_category.pk,
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.SPRINT.id
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 4)

    def test_listing_filtering_nonexistant_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering with a non-existant carrier. It should fall back on
        # region filtering only.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.SPRINT.id
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        eq_(collections[2]['id'], self.collection2.id)

    def test_listing_filtering_nonexistant_carrier_and_region(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering with a non-existant carrier and region. It should
        # fall back on no filtering.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.UK.id,
            'carrier': mkt.carriers.SPRINT.id
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 4)

    def detail(self, client):
        apps = self.apps[:2]
        for app in apps:
            self.collection.add_app(app)
        url = self.collection_url('detail', self.collection.pk)
        res = client.get(url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)

        # Verify that the collection metadata is in tact.
        for field, value in self.collection_data.iteritems():
            eq_(data[field], self.collection_data[field])

        # Verify that the apps are present in the correct order.
        for order, app in enumerate(apps):
            eq_(data['apps'][order]['slug'], app.app_slug)

    def test_detail(self):
        self.detail(self.anon)

    def test_detail_no_perms(self):
        self.detail(self.client)

    def test_detail_has_perms(self):
        self.make_publisher()
        self.detail(self.client)

    def create(self, client):
        res = client.post(self.list_url, json.dumps(self.collection_data))
        data = json.loads(res.content)
        return res, data

    def test_create_anon(self):
        res, data = self.create(self.anon)
        eq_(res.status_code, 403)

    def test_create_no_perms(self):
        res, data = self.create(self.client)
        eq_(res.status_code, 403)

    def test_create_has_perms(self):
        self.make_publisher()
        res, data = self.create(self.client)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        assert new_collection.pk != self.collection.pk

        # Verify that the collection metadata is correct.
        for field, value in self.collection_data.iteritems():
            eq_(data[field], self.collection_data[field])
            eq_(getattr(new_collection, field), self.collection_data[field])

    def test_create_has_perms_no_type(self):
        self.make_publisher()
        self.collection_data.pop('collection_type')
        res, data = self.create(self.client)
        eq_(res.status_code, 400)

    def add_app(self, client, app_id=None):
        if app_id is None:
            app_id = self.apps[0].pk
        form_data = {'app': app_id} if app_id else {}
        url = self.collection_url('add-app', self.collection.pk)
        res = client.post(url, json.dumps(form_data))
        data = json.loads(res.content)
        return res, data

    def test_add_app_anon(self):
        res, data = self.add_app(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_add_app_no_perms(self):
        res, data = self.add_app(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_add_app_has_perms(self):
        self.make_publisher()
        res, data = self.add_app(self.client)
        eq_(res.status_code, 200)

    def test_add_app_nonexistent(self):
        self.make_publisher()
        res, data = self.add_app(self.client, app_id=100000)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['doesnt_exist'], data['detail'])

    def test_add_app_empty(self):
        self.make_publisher()
        res, data = self.add_app(self.client, app_id=False)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['not_provided'], data['detail'])

    def test_add_app_duplicate(self):
        self.make_publisher()
        self.add_app(self.client)
        res, data = self.add_app(self.client)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['already_in'], data['detail'])

    def remove_app(self, client, app_id=None):
        if app_id is None:
            app_id = self.apps[0].pk
        form_data = {'app': app_id} if app_id else {}
        url = self.collection_url('remove-app', self.collection.pk)
        remove_res = client.post(url, json.dumps(form_data))
        remove_data = json.loads(remove_res.content)
        return remove_res, remove_data

    def test_remove_app_anon(self):
        res, data = self.remove_app(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_remove_app_no_perms(self):
        res, data = self.remove_app(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_remove_app_has_perms(self):
        self.make_publisher()
        self.add_app(self.client)
        res, data = self.remove_app(self.client)
        eq_(res.status_code, 200)
        eq_(len(data['apps']), 0)

    def test_remove_app_nonexistent(self):
        self.make_publisher()
        res, data = self.remove_app(self.client, app_id=100000)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['doesnt_exist'], data['detail'])

    def test_remove_app_empty(self):
        self.make_publisher()
        res, data = self.remove_app(self.client, app_id=False)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['not_provided'], data['detail'])

    def test_remove_app_invalid(self):
        self.make_publisher()
        self.add_app(self.client)
        res, data = self.remove_app(self.client, app_id=self.apps[1].pk)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['not_in'], data['detail'])

    def edit_collection(self, client, **kwargs):
        url = self.collection_url('detail', self.collection.pk)
        res = client.patch(url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def test_edit_collection_anon(self):
        res, data = self.edit_collection(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_edit_collection_no_perms(self):
        res, data = self.edit_collection(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_edit_collection_has_perms(self):
        self.make_publisher()
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='grumpy-cat')
        updates = {
            'name': u'clôuserw soundboard',
            'description': u'Gèt off my lawn!',
            'author': u'Nöt Me!',
            'region': mkt.regions.SPAIN.id,
            'category': cat.pk,
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        self.collection.reload()

        # Test that the result and object contain the right values. Remove
        # category from the dict first to test it separately.
        updates.pop('category')
        for key, value in updates.iteritems():
            eq_(data[key], value)
            eq_(getattr(self.collection, key), value)
        eq_(data['category'], cat.pk)
        eq_(self.collection.category, cat)

    def test_edit_collection_invalid_carrier(self):
        self.make_publisher()
        # Invalid carrier.
        updates = {'carrier': 1576}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_invalid_region_0(self):
        # 0 is an invalid region. Unfortunately, because django bug #18724 is
        # fixed in django 1.5 but not 1.4, '0' values are accepted.
        # Unskip this test when using django 1.5.
        raise SkipTest('Test that needs django 1.5 to pass')
        self.make_publisher()
        updates = {'region': 0}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_invalid_region(self):
        self.make_publisher()
        # Invalid region id.
        updates = {'region': max(mkt.regions.REGION_IDS) + 1}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_category(self):
        self.make_publisher()
        eq_(Category.objects.count(), 0)
        # Invalid (non-existant) category.
        updates = {'category': 1}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def reorder(self, client, order=None):
        if order is None:
            order = {}
        url = self.collection_url('reorder', self.collection.pk)
        res = client.post(url, json.dumps(order))
        data = json.loads(res.content)
        return res, data

    def random_app_order(self):
        apps = list(a.pk for a in self.apps)
        shuffle(apps)
        return apps

    def test_reorder_anon(self):
        res, data = self.reorder(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_reorder_no_perms(self):
        res, data = self.reorder(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_reorder_has_perms(self):
        self.make_publisher()
        self.add_all_apps()
        new_order = self.random_app_order()
        res, data = self.reorder(self.client, order=new_order)
        eq_(res.status_code, 200)
        for order, app in enumerate(data['apps']):
            app_pk = new_order[order]
            eq_(Webapp.objects.get(pk=app_pk).app_slug, app['slug'])

    def test_reorder_missing_apps(self):
        self.make_publisher()
        self.add_all_apps()
        new_order = self.random_app_order()
        new_order.pop()
        res, data = self.reorder(self.client, order=new_order)
        eq_(res.status_code, 400)
        eq_(data['detail'], CollectionViewSet.exceptions['app_mismatch'])
        self.assertSetEqual([a['slug'] for a in data['apps']],
                            [a.app_slug for a in self.collection.apps()])
