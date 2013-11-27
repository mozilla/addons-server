# -*- coding: utf-8 -*-
import json

from nose.tools import eq_

from django.core.urlresolvers import reverse

import mkt.carriers
import mkt.regions
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection
from mkt.feed.models import FeedItem


class CollectionMixin(object):
    collection_data = {
        'author': u'My Àuthør',
        'collection_type': COLLECTIONS_TYPE_BASIC,
        'is_public': True,
        'name': {'en-US': u'My Favorite Gamés'},
        'slug': u'my-favourite-gamés',
    }

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        super(CollectionMixin, self).setUp()


class BaseTestFeedItemViewSet(RestOAuth):
    def setUp(self):
        super(BaseTestFeedItemViewSet, self).setUp()
        self.profile = self.user.get_profile()

    def feed_permission(self):
        """
        Grant the Feed:Curate permission to the authenticating user.
        """
        self.grant_permission(self.profile, 'Feed:Curate')


class TestFeedItemViewSetList(CollectionMixin, BaseTestFeedItemViewSet):
    """
    Tests the handling of GET requests to the list endpoint of FeedItemViewSet.
    """
    def setUp(self):
        super(TestFeedItemViewSetList, self).setUp()
        self.url = reverse('feeditem-list')
        self.item = FeedItem.objects.create(collection=self.collection)

    def list(self, client, **kwargs):
        res = client.get(self.url, kwargs)
        data = json.loads(res.content)
        return res, data

    def test_list_anonymous(self):
        res, data = self.list(self.anon)
        eq_(res.status_code, 200)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['id'], self.item.id)

    def test_list_no_permission(self):
        res, data = self.list(self.client)
        eq_(res.status_code, 200)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['id'], self.item.id)

    def test_list_with_permission(self):
        self.feed_permission()
        res, data = self.list(self.client)
        eq_(res.status_code, 200)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['id'], self.item.id)


class TestFeedItemViewSetCreate(CollectionMixin, BaseTestFeedItemViewSet):
    """
    Tests the handling of POST requests to the list endpoint of FeedItemViewSet.
    """
    def setUp(self):
        super(TestFeedItemViewSetCreate, self).setUp()
        self.url = reverse('feeditem-list')

    def create(self, client, **kwargs):
        res = client.post(self.url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def test_create_anonymous(self):
        res, data = self.create(self.anon, collection=self.collection.pk)
        eq_(res.status_code, 403)

    def test_create_no_permission(self):
        res, data = self.create(self.client, collection=self.collection.pk)
        eq_(res.status_code, 403)

    def test_create_with_permission(self):
        self.feed_permission()
        res, data = self.create(self.client, collection=self.collection.pk,
                                carrier=mkt.carriers.TELEFONICA.id,
                                region=mkt.regions.BR.id)
        eq_(res.status_code, 201)
        eq_(data['collection']['id'], self.collection.pk)

    def test_create_no_data(self):
        self.feed_permission()
        res, data = self.create(self.client)
        eq_(res.status_code, 400)


class TestFeedItemViewSetDetail(CollectionMixin, BaseTestFeedItemViewSet):
    """
    Tests the handling of GET requests to detail endpoints of FeedItemViewSet.
    """
    def setUp(self):
        super(TestFeedItemViewSetDetail, self).setUp()
        self.item = FeedItem.objects.create(collection=self.collection)
        self.url = reverse('feeditem-detail', kwargs={'pk': self.item.pk})

    def detail(self, client, **kwargs):
        res = client.get(self.url, kwargs)
        data = json.loads(res.content)
        return res, data

    def test_list_anonymous(self):
        res, data = self.detail(self.anon)
        eq_(res.status_code, 200)
        eq_(data['id'], self.item.pk)

    def test_list_no_permission(self):
        res, data = self.detail(self.client)
        eq_(res.status_code, 200)
        eq_(data['id'], self.item.pk)

    def test_list_with_permission(self):
        self.feed_permission()
        res, data = self.detail(self.client)
        eq_(res.status_code, 200)
        eq_(data['id'], self.item.pk)


class TestFeedItemViewSetUpdate(CollectionMixin, BaseTestFeedItemViewSet):
    """
    Tests the handling of PATCH requests to detail endpoints of FeedItemViewSet.
    """
    def setUp(self):
        super(TestFeedItemViewSetUpdate, self).setUp()
        self.item = FeedItem.objects.create(collection=self.collection)
        self.url = reverse('feeditem-detail', kwargs={'pk': self.item.pk})

    def update(self, client, **kwargs):
        res = client.patch(self.url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def test_update_anonymous(self):
        res, data = self.update(self.anon)
        eq_(res.status_code, 403)

    def test_update_no_permission(self):
        res, data = self.update(self.client)
        eq_(res.status_code, 403)

    def test_update_with_permission(self):
        self.feed_permission()
        res, data = self.update(self.client, region=mkt.regions.US.id)
        eq_(res.status_code, 200)
        eq_(data['id'], self.item.pk)
        eq_(data['region'], mkt.regions.US.slug)

    def test_update_no_items(self):
        self.feed_permission()
        res, data = self.update(self.client, collection=None)
        eq_(res.status_code, 400)


class TestFeedItemViewSetDelete(CollectionMixin, BaseTestFeedItemViewSet):
    """
    Tests the handling of DELETE requests to detail endpoints of
    FeedItemViewSet.
    """
    def setUp(self):
        super(TestFeedItemViewSetDelete, self).setUp()
        self.item = FeedItem.objects.create(collection=self.collection)
        self.url = reverse('feeditem-detail', kwargs={'pk': self.item.pk})

    def delete(self, client, **kwargs):
        res = client.delete(self.url)
        data = json.loads(res.content) if res.content else ''
        return res, data

    def test_update_anonymous(self):
        res, data = self.delete(self.anon)
        eq_(res.status_code, 403)

    def test_update_no_permission(self):
        res, data = self.delete(self.client)
        eq_(res.status_code, 403)

    def test_update_with_permission(self):
        self.feed_permission()
        res, data = self.delete(self.client)
        eq_(res.status_code, 204)
