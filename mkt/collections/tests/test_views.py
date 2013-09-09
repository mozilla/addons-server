# -*- coding: utf-8 -*-
import json
import os
from random import shuffle

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import reverse
from django.utils import translation

from PIL import Image
from nose import SkipTest
from nose.tools import eq_, ok_
from rest_framework.exceptions import PermissionDenied

import amo
import amo.tests
import mkt
from addons.models import Category
from amo.utils import slugify
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_FEATURED,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.collections.views import CollectionViewSet
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp

from mkt.collections.tests.test_serializers import IMAGE_DATA, CollectionDataMixin

class TestCollectionViewSetMixin(object):
    def make_publisher(self):
        self.grant_permission(self.profile, 'Apps:Publisher')

    def create(self, client):
        res = client.post(self.list_url, json.dumps(self.collection_data))
        data = json.loads(res.content)
        return res, data

    def duplicate(self, client, data=None):
        if not data:
            data = {}
        url = self.collection_url('duplicate', self.collection.pk)
        res = client.post(url, json.dumps(data))
        data = json.loads(res.content)
        return res, data

    def edit_collection(self, client, **kwargs):
        url = self.collection_url('detail', self.collection.pk)
        res = client.patch(url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def collection_url(self, action, pk):
        return reverse('collections-%s' % action, kwargs={'pk': pk})


class TestCollectionViewSet(TestCollectionViewSetMixin, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionViewSet, self).setUp()
        self.serializer = CollectionSerializer()
        self.collection_data = {
            'author': u'My Àuthør',
            'background_color': '#FFF000',
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'description': {'en-US': u'A cöllection of my favorite games'},
            'is_public': True,
            'name': {'en-US': u'My Favorite Gamés'},
            'slug': u'my-favourite-gamés',
            'text_color': '#000FFF',
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.list_url = reverse('collections-list')

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
        self.category = Category.objects.create(slug='ccc', name='CatCatCat',
                                                type=amo.ADDON_WEBAPP)
        self.empty_category = Category.objects.create(slug='emptycat',
                                                      name='Empty Cat',
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

        self.collection.update(region=mkt.regions.PL.id)

        res = self.client.get(self.list_url, {'region': mkt.regions.SPAIN.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        eq_(collections[2]['id'], self.collection2.id)

    def test_listing_filtering_region_id(self):
        self.create_additional_data()
        self.make_publisher()

        self.collection.update(region=mkt.regions.PL.id)

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
            {'carrier': mkt.carriers.TELEFONICA.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        # self.collection.carrier is None, so it will match too.
        eq_(collections[2]['id'], self.collection.id)

    def test_listing_filtering_carrier_id(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url,
            {'carrier': mkt.carriers.TELEFONICA.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        # self.collection.carrier is None, so it will match too.
        eq_(collections[2]['id'], self.collection.id)

    def test_listing_filtering_carrier_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'carrier': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection.id)

    def test_listing_filtering_region_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'region': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection3.id)
        eq_(collections[1]['id'], self.collection.id)

    def test_listing_filtering_category(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': self.category.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.id)

    def test_listing_filtering_category_id(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': self.category.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.id)

    def test_listing_filtering_category_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection3.id)
        eq_(collections[1]['id'], self.collection2.id)
        eq_(collections[2]['id'], self.collection.id)

    def test_listing_filtering_category_region_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {
            'cat': self.category.slug,
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.SPRINT.slug
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.id)

    def test_listing_filtering_category_region_carrier_fallback(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering with a non-existant category + region + carrier.
        # It should fall back on carrier+category filtering only, not find
        # anything either, then fall back to region+category only, again not
        # find anything, then category only and stop there, still finding no
        # results.
        res = self.client.get(self.list_url, {
            'cat': self.empty_category.slug,
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.SPRINT.slug
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 0)

    def test_listing_filtering_nonexistant_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        Collection.objects.all().update(carrier=mkt.carriers.TELEFONICA.id)
        self.collection.update(region=mkt.regions.PL.id)

        # Test filtering with a carrier that doesn't match any Collection.
        # It should fall back on region filtering only.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.SPRINT.slug
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

        nyan = Category.objects.create(type=amo.ADDON_WEBAPP, name='Nyan Cat',
                                       slug='nyan-cat')

        Collection.objects.all().update(carrier=mkt.carriers.TELEFONICA.id,
                                        region=mkt.regions.SPAIN.id,
                                        category=self.category)
        self.collection.update(category=nyan)

        # Test filtering with a non-existant carrier and region. It should
        # fall back to filtering on category only.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.UK.slug,
            'carrier': mkt.carriers.SPRINT.slug,
            'cat': self.category.pk
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection4.id)
        eq_(collections[1]['id'], self.collection3.id)
        eq_(collections[2]['id'], self.collection2.id)

    def detail(self, client, url=None):
        apps = self.apps[:2]
        for app in apps:
            self.collection.add_app(app)
        if not url:
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

    def test_detail_slug_in_url(self):
        self.detail(self.anon,
            url=self.collection_url('detail', self.collection.slug))

    def test_detail_no_perms(self):
        self.detail(self.client)

    def test_detail_has_perms(self):
        self.make_publisher()
        self.detail(self.client)

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
        ok_(new_collection.pk != self.collection.pk)

        self.collection_data['slug'] = u'my-favourite-gamés-1'

        # Verify that the collection metadata is correct.
        keys = self.collection_data.keys()
        keys.remove('name')
        keys.remove('description')
        for field in keys:
            eq_(data[field], self.collection_data[field])
            eq_(getattr(new_collection, field), self.collection_data[field])

        # Test name and description separately as we return the whole dict
        # with all translations.
        eq_(data['name'], data['name'])
        eq_(new_collection.name, data['name']['en-US'])

        eq_(data['description'], data['description'])
        eq_(new_collection.description, data['description']['en-US'])

    def test_create_no_colors(self):
        self.collection_data['background_color'] = ''
        self.collection_data['text_color'] = ''
        self.test_create_has_perms()

    def test_create_has_perms_no_type(self):
        self.make_publisher()
        self.collection_data.pop('collection_type')
        res, data = self.create(self.client)
        eq_(res.status_code, 400)

    def test_create_has_perms_no_slug(self):
        self.make_publisher()
        self.collection_data.pop('slug')
        res, data = self.create(self.client)
        eq_(res.status_code, 201)
        eq_(data['slug'], slugify(self.collection_data['name']['en-US']))

    def test_create_collection_no_author(self):
        self.make_publisher()
        self.collection_data.pop('author')
        res, data = self.create(self.client)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        ok_(new_collection.pk != self.collection.pk)
        eq_(new_collection.author, '')

    def test_duplicate_anon(self):
        res, data = self.create(self.anon)
        eq_(res.status_code, 403)

    def test_duplicate_no_perms(self):
        res, data = self.create(self.client)
        eq_(res.status_code, 403)

    def test_duplicate_has_perms(self):
        self.make_publisher()
        original = self.collection

        res, data = self.duplicate(self.client)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        ok_(new_collection.pk != original.pk)
        ok_(new_collection.slug)
        ok_(new_collection.slug != original.slug)

        # Verify that the collection metadata is correct. We duplicated
        # self.collection, which was created with self.collection_data, so
        # use that.
        original = self.collection
        keys = self.collection_data.keys()
        keys.remove('name')
        keys.remove('description')
        keys.remove('slug')
        for field in keys:
            eq_(data[field], self.collection_data[field])
            eq_(getattr(new_collection, field), self.collection_data[field])
            eq_(getattr(new_collection, field), getattr(original, field))

        # Test name and description separately as we return the whole dict
        # with all translations.
        eq_(data['name'], self.collection_data['name'])
        eq_(new_collection.name, data['name']['en-US'])
        eq_(new_collection.name, original.name)

        eq_(data['description'], self.collection_data['description'])
        eq_(new_collection.description, data['description']['en-US'])
        eq_(new_collection.description, original.description)

    def test_duplicate_apps(self):
        self.make_publisher()
        apps = self.apps[:2]
        for app in apps:
            self.collection.add_app(app)

        res, data = self.duplicate(self.client)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        ok_(new_collection.pk != self.collection.pk)
        eq_(new_collection.apps(), self.collection.apps())
        eq_(len(data['apps']), len(apps))
        for order, app in enumerate(apps):
            eq_(int(data['apps'][order]['id']), apps[order].id)

    def test_duplicate_override(self):
        self.make_publisher()
        override_data = {
            'collection_type': COLLECTIONS_TYPE_OPERATOR,
            'region': mkt.regions.SPAIN.id
        }
        res, data = self.duplicate(self.client, override_data)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        ok_(new_collection.pk != self.collection.pk)
        for key in override_data:
            eq_(getattr(new_collection, key), override_data[key])
            ok_(getattr(new_collection, key) != getattr(self.collection, key))

        # We return slugs always in data, so test that separately.
        expected_data = {
            'collection_type': COLLECTIONS_TYPE_OPERATOR,
            'region': mkt.regions.SPAIN.slug
        }
        for key in expected_data:
            eq_(data[key], expected_data[key])

    def test_duplicate_invalid_data(self):
        self.make_publisher()
        override_data = {
            'collection_type': COLLECTIONS_TYPE_OPERATOR,
            'region': max(mkt.regions.REGION_IDS) + 1
        }
        res, data = self.duplicate(self.client, override_data)
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
        remove_data = (json.loads(remove_res.content) if remove_res.content else
                       None)
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
        eq_(res.status_code, 205)
        ok_(not data)

    def test_edit_collection_anon(self):
        res, data = self.edit_collection(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_edit_collection_name_and_description_simple(self):
        self.make_publisher()
        updates = {
            'description': u'¿Dónde está la biblioteca?',
            'name': u'Allö',
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        self.collection.reload()
        for key, value in updates.iteritems():
            eq_(data[key], {'en-US': value})
            eq_(getattr(self.collection, key), value)

    def test_edit_collection_name_and_description_multiple_translations(self):
        self.make_publisher()
        updates = {
            'name': {
                'en-US': u'Basta the potato',
                'fr': u'Basta la pomme de terre',
                'es': u'Basta la pâtätà',
                'it': u'Basta la patata'
            },
            'description': {
                'en-US': 'Basta likes potatoes and Le Boulanger',
                'fr': 'Basta aime les patates et Le Boulanger',
                'es': 'Basta gusta las patatas y Le Boulanger',
                'it': 'Basta ama patate e Le Boulanger'
            }
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        self.collection = Collection.objects.get(pk=self.collection.pk)
        for key, value in updates.iteritems():
            eq_(getattr(self.collection, key), updates[key]['en-US'])

        with translation.override('es'):
            collection_in_es = Collection.objects.get(pk=self.collection.pk)
            eq_(getattr(collection_in_es, key), updates[key]['es'])

        with translation.override('fr'):
            collection_in_fr = Collection.objects.get(pk=self.collection.pk)
            eq_(getattr(collection_in_fr, key), updates[key]['fr'])

    def test_edit_collection_has_perms(self):
        self.make_publisher()
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, name='Grumpy',
                                      slug='grumpy-cat')
        updates = {
            'author': u'Nöt Me!',
            'region': mkt.regions.SPAIN.id,
            'is_public': False,
            'name': {'en-US': u'clôuserw soundboard'},
            'description': {'en-US': u'Gèt off my lawn!'},
            'category': cat.pk,
            'carrier': mkt.carriers.TELEFONICA.id,
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        collection = self.collection.reload()

        # Test that the result and object contain the right values. We can't
        # easily loop on updates dict because data is stored and serialized
        # in different ways depending on the field.
        eq_(data['author'], updates['author'])
        eq_(collection.author, updates['author'])

        eq_(data['is_public'], updates['is_public'])
        eq_(collection.is_public, updates['is_public'])

        eq_(data['name'], updates['name'])
        eq_(collection.name, updates['name']['en-US'])

        eq_(data['description'], updates['description'])
        eq_(collection.description, updates['description']['en-US'])

        eq_(data['category'], cat.slug)
        eq_(collection.category, cat)

        eq_(data['region'], mkt.regions.SPAIN.slug)
        eq_(collection.region, updates['region'])

        eq_(data['carrier'], mkt.carriers.TELEFONICA.slug)
        eq_(collection.carrier, updates['carrier'])

    def test_edit_collection_with_slugs(self):
        self.make_publisher()
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, name='Grumpy',
                                      slug='grumpy-cat')
        updates = {
            'region': mkt.regions.SPAIN.slug,
            'category': cat.slug,
            'carrier': mkt.carriers.TELEFONICA.slug,
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        collection = self.collection.reload()

        # Test that the result and object contain the right values. We can't
        # easily loop on updates dict because data is stored and serialized
        # in different ways depending on the field.
        eq_(data['region'], mkt.regions.SPAIN.slug)
        eq_(collection.region, mkt.regions.SPAIN.id)

        eq_(data['carrier'], mkt.carriers.TELEFONICA.slug)
        eq_(collection.carrier, mkt.carriers.TELEFONICA.id)

        eq_(data['category'], cat.slug)
        eq_(collection.category, cat)

    def test_edit_collection_invalid_carrier_slug(self):
        self.make_publisher()
        # Invalid carrier slug.
        updates = {'carrier': 'whateverlol'}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_invalid_carrier(self):
        self.make_publisher()
        # Invalid carrier id.
        updates = {'carrier': 1576}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_null_values(self):
        self.make_publisher()
        cat = Category.objects.create(type=amo.ADDON_WEBAPP, name='Grumpy',
                                      slug='grumpy-cat')
        self.collection.update(**{
            'carrier': mkt.carriers.UNKNOWN_CARRIER.id,
            'region': mkt.regions.SPAIN.id,
            'category': cat,
        })

        updates = {
            'carrier': None,
            'region': None,
            'category': None,
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        self.collection.reload()
        for key, value in updates.iteritems():
            eq_(data[key], value)
            eq_(getattr(self.collection, key), value)

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

    def test_edit_collection_invalid_region_slug(self):
        self.make_publisher()
        # Invalid region slug.
        updates = {'region': 'idontexist'}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_invalid_category(self):
        self.make_publisher()
        eq_(Category.objects.count(), 0)
        # Invalid (non-existant) category.
        updates = {'category': 1}
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)

    def test_edit_collection_invalid_category_slug(self):
        self.make_publisher()
        eq_(Category.objects.count(), 0)
        # Invalid (non-existant) category slug.
        updates = {'category': 'nosuchcat'}
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

    def delete(self, client, collection_id=None):
        url = self.collection_url('detail', collection_id or self.collection.pk)
        res = client.delete(url)
        data = json.loads(res.content) if res.content else None
        return res, data

    def test_delete_anon(self):
        res, data = self.delete(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_delete_no_perms(self):
        res, data = self.delete(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_delete_has_perms(self):
        self.make_publisher()
        res, data = self.delete(self.client)
        eq_(res.status_code, 204)
        ok_(not data)

    def test_delete_nonexistent(self):
        self.make_publisher()
        res, data = self.delete(self.client, collection_id=100000)
        eq_(res.status_code, 404)


class TestCollectionViewSetUnique(TestCollectionViewSetMixin, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionViewSetUnique, self).setUp()
        self.serializer = CollectionSerializer()
        self.category = Category.objects.create(type=amo.ADDON_WEBAPP,
            name='Grumpy', slug='grumpy-cat')
        self.collection_data = {
            'collection_type': COLLECTIONS_TYPE_FEATURED,
            'name': 'Featured Apps are cool',
            'slug': 'featured-apps-are-cool',
            'description': 'Featured Apps really are the bomb',
            'region': mkt.regions.SPAIN.id,
            'carrier': mkt.carriers.TELEFONICA.id,
            'category': self.category,
            'is_public': True,
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.list_url = reverse('collections-list')
        self.grant_permission(self.profile, 'Apps:Publisher')

    def test_create_featured_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when creating a new collection.
        """
        self.collection_data['category'] = self.collection_data['category'].pk
        res, data = self.create(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

    def test_create_featured_duplicate_different_category(self):
        """
        Try to create a new collection with the duplicate data from our
        featured collection, this time changing the category.
        """
        nyan = Category.objects.create(type=amo.ADDON_WEBAPP, name='Nyan Cat',
                                       slug='nyan-cat')
        self.collection_data['category'] = nyan.pk
        res, data = self.create(self.client)
        eq_(res.status_code, 201)

    def test_edit_collection_featured_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when editing a collection.
        """
        self.collection_data.update({
            'region': mkt.regions.US.id,
            'carrier': mkt.carriers.SPRINT.id
        })
        extra_collection = Collection.objects.create(**self.collection_data)

        # Try to edit self.collection with the data from our extra_collection.
        update_data = {
            'region': extra_collection.region,
            'carrier': extra_collection.carrier,
        }
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

        # Changing the collection type should be enough to make it work.
        update_data['collection_type'] = COLLECTIONS_TYPE_OPERATOR
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

    def test_edit_collection_operator_shelf_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when editing a collection.
        """
        self.collection_data.update({
            'collection_type': COLLECTIONS_TYPE_OPERATOR,
        })
        extra_collection = Collection.objects.create(**self.collection_data)

        # Try to edit self.collection with the data from our extra_collection.
        update_data = {'collection_type': extra_collection.collection_type}
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

        # Changing the category should be enough to make it work.
        nyan = Category.objects.create(type=amo.ADDON_WEBAPP, name='Nyan Cat',
                                      slug='nyan-cat')
        update_data['category'] = nyan.pk
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

    def test_duplicate_featured(self):
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

    def test_duplicate_operator(self):
        self.collection.update(collection_type=COLLECTIONS_TYPE_OPERATOR)
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)


class TestCollectionImageViewSet(RestOAuth):

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionImageViewSet, self).setUp()
        self.collection = Collection.objects.create(
            **CollectionDataMixin.collection_data)
        self.url = reverse('collection-image-detail',
                           kwargs={'pk': self.collection.pk})

    def test_put(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res = self.client.put(self.url, 'data:image/gif;base64,' + IMAGE_DATA)
        eq_(res.status_code, 204)
        assert os.path.exists(self.collection.image_path())
        im = Image.open(self.collection.image_path())
        im.verify()
        assert im.format == 'PNG'

    def test_put_non_data_uri(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res = self.client.put(self.url, 'some junk')
        eq_(res.status_code, 400)

    def test_put_non_image(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res = self.client.put(self.url, 'data:text/plain;base64,AAA=')
        eq_(res.status_code, 400)

    def test_put_unauthorized(self):
        res = self.client.put(self.url, 'some junk')
        eq_(res.status_code, 403)

    def test_get(self):
        if not settings.XSENDFILE:
            raise SkipTest
        img = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEUAAACnej'
               '3aAAAAAXRSTlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAASUVORK5C'
               'YII=').decode('base64')
        path = self.collection.image_path()
        storage.open(path, 'w').write(img)
        res = self.client.get(self.url)
        eq_(res[settings.XSENDFILE_HEADER], path)
