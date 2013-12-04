# -*- coding: utf-8 -*-
import json
import os
from random import shuffle
from urlparse import urlparse

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import reverse
from django.http import QueryDict
from django.utils import translation

from nose import SkipTest
from nose.tools import eq_, ok_
from PIL import Image
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
from mkt.collections.views import CollectionViewSet
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp

from mkt.collections.tests.test_serializers import (CollectionDataMixin,
                                                    IMAGE_DATA)
from users.models import UserProfile


class BaseCollectionViewSetTest(RestOAuth):
    """
    Base class for all CollectionViewSet tests.
    """
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(BaseCollectionViewSetTest, self).setUp()
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
        self.apps = []
        self.list_url = reverse('collections-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=999)

    def setup_unique(self):
        """
        Additional setup required to test collection category/region/carrier
        uniqueness constraints.
        """
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
        self.grant_permission(self.profile, 'Collections:Curate')

    def create_apps(self, number=1):
        """
        Create `number` apps, adding them to `self.apps`.
        """
        for n in xrange(0, number):
            self.apps.append(amo.tests.app_factory())

    def add_apps_to_collection(self, *args):
        """
        Add each app passed to `*args` to `self.collection`.
        """
        for app in args:
            self.collection.add_app(app)

    def make_curator(self):
        """
        Make the authenticating user a curator on self.collection.
        """
        self.collection.add_curator(self.profile)

    def make_publisher(self):
        """
        Grant the Collections:Curate permission to the authenticating user.
        """
        self.grant_permission(self.profile, 'Collections:Curate')

    def collection_url(self, action, pk):
        """
        Return the URL to a collection API endpoint with primary key `pk` to do
        action `action`.
        """
        return reverse('collections-%s' % action, kwargs={'pk': pk})

    def create_additional_data(self):
        """
        Creates two additional categories and three additional collections.
        """
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


class TestCollectionViewSetListing(BaseCollectionViewSetTest):
    """
    Tests the handling of GET requests to the list endpoint of
    CollectionViewSet.
    """
    def listing(self, client):
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
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

    def test_listing(self):
        self.listing(self.anon)

    def test_listing_no_perms(self):
        self.listing(self.client)

    def test_listing_has_perms(self):
        self.make_publisher()
        self.listing(self.client)

    def test_listing_curator(self):
        self.make_curator()
        self.listing(self.client)

    def test_listing_single_lang(self):
        self.collection.name = {
            'fr': u'Basta la pomme de terre frite',
        }
        self.collection.save()
        res = self.client.get(self.list_url, {'lang': 'fr'})
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        collection = data['objects'][0]
        eq_(collection['name'], u'Basta la pomme de terre frite')
        eq_(collection['description'], u'A cöllection of my favorite games')

    def test_listing_filter_unowned_hidden(self):
        """
        Hidden collections that you do not own should not be returned.
        """
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
        self.collection.update(is_public=False)
        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(len(data['objects']), 0)

    def test_listing_filter_owned_hidden(self):
        """
        Hidden collections that you do own should be returned.
        """
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
        self.collection.update(is_public=False)
        self.collection.curators.add(self.user)
        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(len(data['objects']), 1)

    def test_listing_pagination(self):
        self.create_additional_data()
        self.make_publisher()  # To be able to see non-public collections.
        res = self.client.get(self.list_url, {'limit': 3})
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 3)
        eq_(data['objects'][0]['id'], self.collection4.pk)
        eq_(data['objects'][1]['id'], self.collection3.pk)
        eq_(data['objects'][2]['id'], self.collection2.pk)
        eq_(data['meta']['total_count'], 4)
        eq_(data['meta']['limit'], 3)
        eq_(data['meta']['previous'], None)
        eq_(data['meta']['offset'], 0)
        next = urlparse(data['meta']['next'])
        ok_(next.path.startswith('/api/v1'))
        eq_(next.path, self.list_url)
        eq_(QueryDict(next.query).dict(), {u'limit': u'3', u'offset': u'3'})

        res = self.client.get(self.list_url, {'limit': 3, 'offset': 3})
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['id'], self.collection.pk)
        eq_(data['meta']['total_count'], 4)
        eq_(data['meta']['limit'], 3)
        prev = urlparse(data['meta']['previous'])
        ok_(prev.path.startswith('/api/v1'))
        eq_(next.path, self.list_url)
        eq_(QueryDict(prev.query).dict(), {u'limit': u'3', u'offset': u'0'})
        eq_(data['meta']['offset'], 3)
        eq_(data['meta']['next'], None)

    def test_listing_no_filtering(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 4)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_error(self):
        res = self.client.get(self.list_url, {'region': 'whateverdude'})
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['detail'], 'Filtering error.')
        errors = data['filter_errors']
        ok_(errors['region'][0].startswith('Select a valid choice.'))

    def test_listing_filtering_region(self):
        self.create_additional_data()
        self.make_publisher()

        self.collection.update(region=mkt.regions.PL.id)

        res = self.client.get(self.list_url,
                              {'region': mkt.regions.SPAIN.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection4.pk)
        eq_(collections[1]['id'], self.collection2.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_region_id(self):
        self.create_additional_data()
        self.make_publisher()

        self.collection.update(region=mkt.regions.PL.id)

        res = self.client.get(self.list_url,
                              {'region': mkt.regions.SPAIN.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection4.pk)
        eq_(collections[1]['id'], self.collection2.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url,
            {'carrier': mkt.carriers.TELEFONICA.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection4.pk)
        eq_(collections[1]['id'], self.collection3.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_carrier_id(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url,
            {'carrier': mkt.carriers.TELEFONICA.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection4.pk)
        eq_(collections[1]['id'], self.collection3.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_carrier_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'carrier': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_carrier_0(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url,
            {'carrier': mkt.carriers.UNKNOWN_CARRIER.id})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection2.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_region_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'region': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 2)
        eq_(collections[0]['id'], self.collection3.pk)
        eq_(collections[1]['id'], self.collection.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_category(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': self.category.slug})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_category_id(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': self.category.pk})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_category_null(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {'cat': ''})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 3)
        eq_(collections[0]['id'], self.collection3.pk)
        eq_(collections[1]['id'], self.collection2.pk)
        eq_(collections[2]['id'], self.collection.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_category_region_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        res = self.client.get(self.list_url, {
            'cat': self.category.slug,
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.TELEFONICA.slug
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection4.pk)
        ok_('API-Fallback' not in res)

    def test_listing_filtering_category_region_carrier_fallback(self):
        self.create_additional_data()
        self.make_publisher()

        # Test filtering with a non-existant category + region + carrier.
        # It should fall back on category + carrier + region=NULL, not find
        # anything either, then fall back to category + region + carrier=NULL,
        # again not find anything, then category + region=NULL + carrier=NULL,
        # and stop there, still finding no results.
        res = self.client.get(self.list_url, {
            'cat': self.empty_category.slug,
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.SPRINT.slug
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 0)
        eq_(res['API-Fallback'], 'region,carrier')

    def test_listing_filtering_nonexistant_carrier(self):
        self.create_additional_data()
        self.make_publisher()

        Collection.objects.all().update(carrier=mkt.carriers.TELEFONICA.id)
        self.collection.update(region=mkt.regions.SPAIN.id, carrier=None)

        # Test filtering with a region+carrier that doesn't match any
        # Collection. It should fall back on region=NULL+carrier, not find
        # anything, then fallback on carrier=NULL+region and find the
        # Collection left in spain with no carrier.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.SPAIN.slug,
            'carrier': mkt.carriers.SPRINT.slug
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection.pk)
        eq_(res['API-Fallback'], 'carrier')

    def test_listing_filtering_nonexistant_carrier_and_region(self):
        self.create_additional_data()
        self.make_publisher()

        nyan = Category.objects.create(type=amo.ADDON_WEBAPP, name='Nyan Cat',
                                       slug='nyan-cat')

        Collection.objects.all().update(carrier=None, region=None,
                                        category=nyan)
        self.collection.update(category=self.category)

        # Test filtering with a non-existant carrier and region. It should
        # go through all fallback till ending up filtering on category +
        # carrier=NULL + region=NULL.
        res = self.client.get(self.list_url, {
            'region': mkt.regions.UK.slug,
            'carrier': mkt.carriers.SPRINT.slug,
            'cat': self.category.pk
        })
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        collections = data['objects']
        eq_(len(collections), 1)
        eq_(collections[0]['id'], self.collection.pk)
        eq_(res['API-Fallback'], 'region,carrier')


class TestCollectionViewSetDetail(BaseCollectionViewSetTest):
    """
    Tests the handling of GET requests to a single collection on
    CollectionViewSet.
    """
    def detail(self, client, url=None):
        self.create_apps(number=2)
        self.add_apps_to_collection(*self.apps)
        if not url:
            url = self.collection_url('detail', self.collection.pk)
        res = client.get(url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)

        # Verify that the collection metadata is in tact.
        for field, value in self.collection_data.iteritems():
            eq_(data[field], self.collection_data[field])

        # Verify that the apps are present in the correct order.
        for order, app in enumerate(self.apps):
            eq_(data['apps'][order]['slug'], app.app_slug)

        return res, data

    def test_detail_filtering(self):
        self.collection.update(region=mkt.regions.SPAIN.id)
        url = self.collection_url('detail', self.collection.pk)
        res = self.client.get(url, {
            'region': mkt.regions.WORLDWIDE.slug
        })
        # Filtering should not be applied.
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['id'], self.collection.pk)
        ok_('API-Fallback' not in res)

    def test_detail(self):
        res, data = self.detail(self.anon)
        ok_(not data['image'])

    def test_detail_image(self):
        storage.open(self.collection.image_path(), 'w').write(IMAGE_DATA)
        self.collection.update(has_image=True)
        res, data = self.detail(self.anon)
        ok_(data['image'])

    def test_detail_slug_in_url(self):
        self.detail(self.anon,
            url=self.collection_url('detail', self.collection.slug))

    def test_detail_no_perms(self):
        self.detail(self.client)

    def test_detail_has_perms(self):
        self.make_publisher()
        self.detail(self.client)

    def test_detail_curator(self):
        self.make_curator()
        self.detail(self.client)


class TestCollectionViewSetCreate(BaseCollectionViewSetTest):
    """
    Tests the handling of POST requests to the list endpoint of
    CollectionViewSet.
    """
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

    def test_create_curator(self):
        self.make_curator
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

    def test_create_validation_operatorshelf_category(self):
        self.category = Category.objects.create(type=amo.ADDON_WEBAPP,
            name='Grumpy', slug='grumpy-cat')
        self.make_publisher()
        self.collection_data.update({
            'category': self.category.pk,
            'collection_type': COLLECTIONS_TYPE_OPERATOR
        })
        res, data = self.create(self.client)
        ok_(res.status_code, 400)
        ok_('non_field_errors' in data.keys())

    def test_create_empty_description_dict_in_default_language(self):
        """
        Test that we can't have an empty Translation for the default_language.
        """
        # See bug https://bugzilla.mozilla.org/show_bug.cgi?id=915652
        raise SkipTest
        self.make_publisher()
        self.collection_data = {
            'collection_type': COLLECTIONS_TYPE_BASIC,
            'name': 'whatever',
            'description': {'en-US': '  ', 'fr': 'lol'},
        }
        res, data = self.create(self.client)
        # The description dict is not empty, but it contains an empty
        # translation for en-US, which is incorrect since it's the default
        # language (it'll save ok, but then fail when reloading).
        # It could work if translation system wasn't insisting on
        # loading only the default+current language...
        eq_(res.status_code, 400)
        ok_('description' in data)

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

    def test_create_featured_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when creating a new collection.
        """
        self.setup_unique()
        self.collection_data['category'] = self.collection_data['category'].pk
        res, data = self.create(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

    def test_create_featured_duplicate_different_category(self):
        """
        Try to create a new collection with the duplicate data from our
        featured collection, this time changing the category.
        """
        self.setup_unique()
        nyan = Category.objects.create(type=amo.ADDON_WEBAPP, name='Nyan Cat',
                                       slug='nyan-cat')
        self.collection_data['category'] = nyan.pk
        res, data = self.create(self.client)
        eq_(res.status_code, 201)


class TestCollectionViewSetDelete(BaseCollectionViewSetTest):
    """
    Tests the handling of DELETE requests to a single collection on
    CollectionViewSet.
    """
    def delete(self, client, collection_id=None):
        url = self.collection_url('detail',
                                  collection_id or self.collection.pk)
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

    def test_delete_curator(self):
        self.make_curator()
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


class TestCollectionViewSetDuplicate(BaseCollectionViewSetTest):
    """
    Tests the `duplicate` action on CollectionViewSet.
    """
    def duplicate(self, client, data=None):
        if not data:
            data = {}
        url = self.collection_url('duplicate', self.collection.pk)
        res = client.post(url, json.dumps(data))
        data = json.loads(res.content)
        return res, data

    def test_duplicate_anon(self):
        res, data = self.duplicate(self.anon)
        eq_(res.status_code, 403)

    def test_duplicate_no_perms(self):
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 403)

    def test_duplicate_curator(self):
        self.make_curator()
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 201)

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
        self.create_apps(number=2)
        self.add_apps_to_collection(*self.apps)
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 201)
        new_collection = Collection.objects.get(pk=data['id'])
        ok_(new_collection.pk != self.collection.pk)
        eq_(list(new_collection.apps()), list(self.collection.apps()))
        eq_(len(data['apps']), len(self.apps))
        for order, app in enumerate(self.apps):
            eq_(int(data['apps'][order]['id']), self.apps[order].pk)

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

    def test_duplicate_featured(self):
        self.setup_unique()
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

    def test_duplicate_operator(self):
        self.setup_unique()
        self.collection.update(collection_type=COLLECTIONS_TYPE_OPERATOR,
                               carrier=None, category=None)
        res, data = self.duplicate(self.client)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)


class CollectionViewSetChangeAppsMixin(BaseCollectionViewSetTest):
    """
    Mixin containing common methods to actions that modify the apps belonging
    to a collection.
    """
    def add_app(self, client, app_id=None):
        if app_id is None:
            self.create_apps()
            app_id = self.apps[0].pk
        form_data = {'app': app_id} if app_id else {}
        url = self.collection_url('add-app', self.collection.pk)
        res = client.post(url, json.dumps(form_data))
        data = json.loads(res.content)
        return res, data

    def remove_app(self, client, app_id=None):
        if app_id is None:
            self.create_apps(number=2)
            app_id = self.apps[0].pk
        form_data = {'app': app_id} if app_id else {}
        url = self.collection_url('remove-app', self.collection.pk)
        remove_res = client.post(url, json.dumps(form_data))
        remove_data = (json.loads(remove_res.content)
                       if remove_res.content else None)
        return remove_res, remove_data

    def reorder(self, client, order=None):
        if order is None:
            order = {}
        url = self.collection_url('reorder', self.collection.pk)
        res = client.post(url, json.dumps(order))
        data = json.loads(res.content)
        return res, data


class TestCollectionViewSetAddApp(CollectionViewSetChangeAppsMixin):
    """
    Tests the `add-app` action on CollectionViewSet.
    """
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

    def test_add_app_curator(self):
        self.make_curator()
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


class TestCollectionViewSetRemoveApp(CollectionViewSetChangeAppsMixin):
    """
    Tests the `remove-app` action on CollectionViewSet.
    """
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

    def test_remove_app_curator(self):
        self.make_curator()
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
        self.create_apps(number=2)
        self.add_app(self.client, app_id=self.apps[0].pk)
        res, data = self.remove_app(self.client, app_id=self.apps[1].pk)
        eq_(res.status_code, 205)
        ok_(not data)


class TestCollectionViewSetReorderApps(CollectionViewSetChangeAppsMixin):
    """
    Tests the `reorder` action on CollectionViewSet.
    """
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
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
        new_order = self.random_app_order()
        res, data = self.reorder(self.client, order=new_order)
        eq_(res.status_code, 200)
        for order, app in enumerate(data['apps']):
            app_pk = new_order[order]
            eq_(Webapp.objects.get(pk=app_pk).app_slug, app['slug'])

    def test_reorder_curator(self):
        self.make_curator()
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
        new_order = self.random_app_order()
        res, data = self.reorder(self.client, order=new_order)
        eq_(res.status_code, 200)
        for order, app in enumerate(data['apps']):
            app_pk = new_order[order]
            eq_(Webapp.objects.get(pk=app_pk).app_slug, app['slug'])

    def test_reorder_missing_apps(self):
        self.make_publisher()
        self.create_apps()
        self.add_apps_to_collection(*self.apps)
        new_order = self.random_app_order()
        new_order.pop()
        res, data = self.reorder(self.client, order=new_order)
        eq_(res.status_code, 400)
        eq_(data['detail'], CollectionViewSet.exceptions['app_mismatch'])
        self.assertSetEqual([a['slug'] for a in data['apps']],
                            [a.app_slug for a in self.collection.apps()])


class TestCollectionViewSetEditCollection(BaseCollectionViewSetTest):
    """
    Tests the handling of PATCH requests to a single collection on
    CollectionViewSet.
    """
    def edit_collection(self, client, **kwargs):
        url = self.collection_url('detail', self.collection.pk)
        res = client.patch(url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

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

    def test_edit_collection_name_and_description_curator(self):
        self.make_curator()
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

    def test_edit_collection_name_strip(self):
        self.make_publisher()
        updates = {
            'name': {
                'en-US': u'  New Nâme! '
            },
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 200)
        self.collection = Collection.objects.get(pk=self.collection.pk)
        eq_(data['name'], {u'en-US': u'New Nâme!'})
        eq_(self.collection.name, u'New Nâme!')

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

    def test_edit_collection_featured_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when editing a collection.
        """
        self.setup_unique()
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
        update_data['collection_type'] = COLLECTIONS_TYPE_BASIC
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

        # A dumb change to see if you can still edit afterwards. The uniqueness
        # check should exclude the current instance and allow it, obviously.
        update_data = {'is_public': False}
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

    def test_edit_collection_operator_shelf_duplicate(self):
        """
        Featured Apps & Operator Shelf should not have duplicates for a
        region / carrier / category combination. Make sure this is respected
        when editing a collection.
        """
        self.setup_unique()
        self.collection.update(category=None,
                               collection_type=COLLECTIONS_TYPE_OPERATOR)
        self.collection_data.update({
            'category': None,
            'collection_type': COLLECTIONS_TYPE_OPERATOR,
            'carrier': mkt.carriers.VIMPELCOM.id,
        })
        extra_collection = Collection.objects.create(**self.collection_data)

        # Try to edit self.collection with the data from our extra_collection.
        update_data = {'carrier': extra_collection.carrier}
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 400)
        ok_('collection_uniqueness' in data)

        # Changing the carrier should be enough to make it work.
        update_data['carrier'] = mkt.carriers.SPRINT.id
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

        # A dumb change to see if you can still edit afterwards. The uniqueness
        # check should exclude the current instance and allow it, obviously.
        update_data = {'is_public': False}
        res, data = self.edit_collection(self.client, **update_data)
        eq_(res.status_code, 200)

    def test_edit_collection_validation_operatorshelf_category(self):
        self.make_publisher()
        category = Category.objects.create(type=amo.ADDON_WEBAPP,
            name='Grumpy', slug='grumpy-cat')
        updates = {
            'category': category.pk,
            'collection_type': COLLECTIONS_TYPE_OPERATOR
        }
        res, data = self.edit_collection(self.client, **updates)
        eq_(res.status_code, 400)
        ok_('non_field_errors' in data)


class TestCollectionViewSetListCurators(BaseCollectionViewSetTest):
    """
    Tests the `curators` action on CollectionViewSet.
    """
    def list_curators(self, client):
        self.collection.add_curator(self.user2)
        url = self.collection_url('curators', self.collection.pk)
        res = client.get(url)
        data = json.loads(res.content)
        return res, data

    def test_list_curators_no_perms(self):
        res, data = self.list_curators(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_list_curators_has_perms(self):
        self.make_publisher()
        res, data = self.list_curators(self.client)
        eq_(res.status_code, 200)
        eq_(len(data), 1)
        eq_(data[0]['id'], self.user2.pk)

    def test_list_curators_as_curator(self):
        self.make_curator()
        res, data = self.list_curators(self.client)
        eq_(res.status_code, 200)
        eq_(len(data), 2)
        for item in data:
            ok_(item['id'] in [self.user.pk, self.user2.pk])


class TestCollectionViewSetAddCurator(BaseCollectionViewSetTest):
    """
    Tests the `add-curator` action on CollectionViewSet.
    """
    def add_curator(self, client, user_id=None):
        if user_id is None:
            user_id = self.user.pk
        form_data = {'user': user_id} if user_id else {}
        url = self.collection_url('add-curator', self.collection.pk)
        res = client.post(url, json.dumps(form_data))
        data = json.loads(res.content)
        return res, data

    def test_add_curator_anon(self):
        res, data = self.add_curator(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_add_curator_no_perms(self):
        res, data = self.add_curator(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_add_curator_has_perms(self):
        self.make_publisher()
        res, data = self.add_curator(self.client)
        eq_(res.status_code, 200)
        eq_(data[0]['id'], self.user.pk)

    def test_add_curator_multiple_cache(self):
        self.make_publisher()
        self.add_curator(self.client)
        res, data = self.add_curator(self.client, user_id=self.user2.pk)
        self.assertSetEqual([user['id'] for user in data],
                            [self.user.pk, self.user2.pk])

    def test_add_curator_as_curator(self):
        self.make_curator()
        res, data = self.add_curator(self.client)
        eq_(res.status_code, 200)
        eq_(data[0]['id'], self.user.pk)

    def test_add_curator_nonexistent(self):
        self.make_publisher()
        res, data = self.add_curator(self.client, user_id=100000)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_doesnt_exist'], data['detail'])

        res, data = self.add_curator(self.client, user_id='doesnt@exi.st')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_doesnt_exist'], data['detail'])

    def test_add_curator_empty(self):
        self.make_publisher()
        res, data = self.add_curator(self.client, user_id=False)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_not_provided'], data['detail'])

    def test_add_curator_email(self):
        self.make_curator()
        res, data = self.add_curator(self.client, user_id=self.user.email)
        eq_(res.status_code, 200)
        eq_(data[0]['id'], self.user.pk)

    def test_add_curator_garbage(self):
        self.make_publisher()
        res, data = self.add_curator(self.client, user_id='garbage')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['wrong_user_format'], data['detail'])

        res, data = self.add_curator(self.client, user_id='garbage@')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['wrong_user_format'], data['detail'])


class TestCollectionViewSetRemoveCurator(BaseCollectionViewSetTest):
    """
    Tests the `remove-curator` action on CollectionViewSet.
    """
    def remove_curator(self, client, user_id=None):
        if user_id is None:
            user_id = self.user.pk
        form_data = {'user': user_id} if user_id else {}
        url = self.collection_url('remove-curator', self.collection.pk)
        res = client.post(url, json.dumps(form_data))
        data = json.loads(res.content) if res.content else None
        return res, data

    def test_remove_curator_anon(self):
        res, data = self.remove_curator(self.anon)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_remove_curator_no_perms(self):
        res, data = self.remove_curator(self.client)
        eq_(res.status_code, 403)
        eq_(PermissionDenied.default_detail, data['detail'])

    def test_remove_curator_has_perms(self):
        self.make_publisher()
        res, data = self.remove_curator(self.client)
        eq_(res.status_code, 205)

    def test_remove_curator_as_curator(self):
        self.make_curator()
        res, data = self.remove_curator(self.client)
        eq_(res.status_code, 205)

    def test_remove_curator_email(self):
        self.make_curator()
        res, data = self.remove_curator(self.client, user_id=self.user.email)
        eq_(res.status_code, 205)

    def test_remove_curator_nonexistent(self):
        self.make_publisher()
        res, data = self.remove_curator(self.client, user_id=100000)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_doesnt_exist'], data['detail'])

        res, data = self.remove_curator(self.client, user_id='doesnt@exi.st')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_doesnt_exist'], data['detail'])

    def test_remove_curator_empty(self):
        self.make_publisher()
        res, data = self.remove_curator(self.client, user_id=False)
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['user_not_provided'], data['detail'])

    def test_remove_curator_garbage(self):
        self.make_publisher()
        res, data = self.remove_curator(self.client, user_id='garbage')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['wrong_user_format'], data['detail'])

        res, data = self.remove_curator(self.client, user_id='garbage@')
        eq_(res.status_code, 400)
        eq_(CollectionViewSet.exceptions['wrong_user_format'], data['detail'])


class TestCollectionImageViewSet(RestOAuth):
    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionImageViewSet, self).setUp()
        self.collection = Collection.objects.create(
            **CollectionDataMixin.collection_data)
        self.url = reverse('collection-image-detail',
                           kwargs={'pk': self.collection.pk})
        self.img = (
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEUAAA'
            'Cnej3aAAAAAXRSTlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAA'
            'SUVORK5CYII=').decode('base64')

    def add_img(self):
        path = self.collection.image_path()
        storage.open(path, 'w').write(self.img)
        self.collection.update(has_image=True)
        return path

    def test_put(self):
        self.grant_permission(self.profile, 'Collections:Curate')
        res = self.client.put(self.url, 'data:image/gif;base64,' + IMAGE_DATA)
        eq_(res.status_code, 204)
        assert os.path.exists(self.collection.image_path())
        ok_(Collection.objects.get(pk=self.collection.pk).has_image)
        im = Image.open(self.collection.image_path())
        im.verify()
        assert im.format == 'PNG'

    def test_put_non_data_uri(self):
        self.grant_permission(self.profile, 'Collections:Curate')
        res = self.client.put(self.url, 'some junk')
        eq_(res.status_code, 400)
        ok_(not Collection.objects.get(pk=self.collection.pk).has_image)

    def test_put_non_image(self):
        self.grant_permission(self.profile, 'Collections:Curate')
        res = self.client.put(self.url, 'data:text/plain;base64,AAA=')
        eq_(res.status_code, 400)
        ok_(not Collection.objects.get(pk=self.collection.pk).has_image)

    def test_put_unauthorized(self):
        res = self.client.put(self.url, 'some junk')
        eq_(res.status_code, 403)

    def test_get(self):
        if not settings.XSENDFILE:
            raise SkipTest
        img_path = self.add_img()
        res = self.client.get(self.url)
        eq_(res[settings.XSENDFILE_HEADER], img_path)

    def test_get_no_image(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_delete(self):
        self.grant_permission(self.profile, 'Collections:Curate')
        img_path = self.add_img()
        res = self.client.delete(self.url)
        eq_(res.status_code, 204)
        ok_(not self.collection.reload().has_image)
        ok_(not storage.exists(img_path))

    def test_delete_unauthorized(self):
        res = self.client.delete(self.url)
        eq_(res.status_code, 403)
