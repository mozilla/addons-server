# -*- coding: utf-8 -*-
import json

from nose.exc import SkipTest
from nose.tools import eq_, ok_

from django.core.urlresolvers import reverse

import mkt.carriers
import mkt.regions
from addons.models import Preview
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection
from mkt.feed.models import FeedApp, FeedItem
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from reviews.models import Review


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


class FeedAppMixin(object):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.feedapp_data = {
            'app': 337141,
            'description': {
                'en-US': u'pan-fried potatoes',
                'fr': u'pommes de terre sautées'
            },
        }
        self.feedapps = []
        super(FeedAppMixin, self).setUp()

    def create_feedapps(self, n=2, **kwargs):
        data = dict(self.feedapp_data)
        data.update(kwargs)
        if not isinstance(data['app'], Webapp):
            data['app'] = Webapp.objects.get(pk=data['app'])
        feedapps = [FeedApp.objects.create(**data) for idx in xrange(n)]
        self.feedapps.extend(feedapps)
        return feedapps


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


class BaseTestFeedAppViewSet(FeedAppMixin, RestOAuth):
    fixtures = FeedAppMixin.fixtures + RestOAuth.fixtures

    def setUp(self):
        super(BaseTestFeedAppViewSet, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.profile = self.user.get_profile()

    def feed_permission(self):
        """
        Grant the Feed:Curate permission to the authenticating user.
        """
        self.grant_permission(self.profile, 'Feed:Curate')


class TestFeedAppViewSetList(BaseTestFeedAppViewSet):
    """
    Tests the handling of GET requests to the list endpoint of FeedAppViewSet.
    """
    num = 2

    def setUp(self):
        super(TestFeedAppViewSetList, self).setUp()
        self.url = reverse('feedapp-list')
        self.create_feedapps(self.num)

    def list(self, client):
        res = client.get(self.url)
        data = json.loads(res.content)
        return res, data

    def _test_list(self, client):
        res, data = self.list(client)
        eq_(res.status_code, 200)
        objects = data['objects']
        eq_(data['meta']['total_count'], self.num)
        eq_(len(objects), self.num)
        self.assertSetEqual([obj['id'] for obj in objects],
                            [fa.id for fa in self.feedapps])

    def test_list_anonymous(self):
        self._test_list(self.anon)

    def test_list_no_permission(self):
        self._test_list(self.client)

    def test_list_with_permission(self):
        self.feed_permission()
        self._test_list(self.client)


class TestFeedAppViewSetCreate(BaseTestFeedAppViewSet):
    """
    Tests the handling of POST requests to the list endpoint of FeedAppViewSet.
    """
    fixtures = BaseTestFeedAppViewSet.fixtures

    def setUp(self):
        super(TestFeedAppViewSetCreate, self).setUp()
        self.url = reverse('feedapp-list')

    def create(self, client, **kwargs):
        res = client.post(self.url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def test_create_anonymous(self):
        res, data = self.create(self.anon)
        eq_(res.status_code, 403)

    def test_create_no_permission(self):
        res, data = self.create(self.client, **self.feedapp_data)
        eq_(res.status_code, 403)

    def test_create_with_permission(self):
        self.feed_permission()
        res, data = self.create(self.client, **self.feedapp_data)
        eq_(res.status_code, 201)
        eq_(data['app']['id'], self.feedapp_data['app'])
        eq_(data['description'], self.feedapp_data['description'])
        return res, data

    def test_create_with_preview(self):
        preview = Preview.objects.create(addon=self.app, position=0)
        self.feedapp_data.update(preview=preview.pk)
        res, data = self.test_create_with_permission()
        eq_(data['preview']['id'], preview.id)

    def test_create_with_rating(self):
        rating = Review.objects.create(**{
            'addon': self.app,
            'user': self.user.get_profile(),
            'version': self.app._latest_version,
            'body': u'I lôve this app',
            'rating': 5
        })
        self.feedapp_data.update(rating=rating.pk)
        res, data = self.test_create_with_permission()
        eq_(data['rating']['user']['display_name'], rating.user.display_name)
        eq_(data['rating']['app'],
            reverse('app-detail', kwargs={'pk': self.app.pk}))

    def test_create_no_data(self):
        self.feed_permission()
        res, data = self.create(self.client)
        eq_(res.status_code, 400)


class TestFeedAppViewSetDetail(BaseTestFeedAppViewSet):
    """
    Tests the handling of GET requests to detail endpoints of FeedAppViewSet.
    """
    def setUp(self):
        super(TestFeedAppViewSetDetail, self).setUp()
        self.feedapp = self.create_feedapps(1)[0]
        self.url = reverse('feedapp-detail', kwargs={'pk': self.feedapp.pk})

    def detail(self, client, **kwargs):
        res = client.get(self.url)
        data = json.loads(res.content)
        return res, data

    def _test_detail(self, client):
        res, data = self.detail(client)
        eq_(res.status_code, 200)
        eq_(data['id'], self.feedapp.pk)
        eq_(data['url'], self.url)
        eq_(data['app']['id'], self.feedapp.app.id)
        ok_(not data['preview'])
        ok_(not data['rating'])

    def test_detail_anonymous(self):
        self._test_detail(self.anon)

    def test_detail_no_permission(self):
        self._test_detail(self.client)

    def test_detail_with_permission(self):
        self.feed_permission()
        self._test_detail(self.client)


class TestFeedAppViewSetUpdate(BaseTestFeedAppViewSet):
    """
    Tests the handling of PATCH requests to detail endpoints of FeedAppViewSet.
    """
    fixtures = BaseTestFeedAppViewSet.fixtures

    def setUp(self):
        super(TestFeedAppViewSetUpdate, self).setUp()
        self.feedapp = self.create_feedapps(1)[0]
        self.url = reverse('feedapp-detail', kwargs={'pk': self.feedapp.pk})

    def update(self, client, **kwargs):
        res = client.patch(self.url, json.dumps(kwargs))
        data = json.loads(res.content)
        return res, data

    def test_update_anonymous(self):
        res, data = self.update(self.anon)
        eq_(res.status_code, 403)

    def test_update_no_permission(self):
        res, data = self.update(self.client, **self.feedapp_data)
        eq_(res.status_code, 403)

    def test_update_with_permission(self):
        self.feed_permission()
        new_description = {
            'en-US': u"BastaCorp's famous pan-fried potatoes",
            'fr': u'pommes de terre sautées de BastaCorp'
        }
        res, data = self.update(self.client, description=new_description)
        eq_(res.status_code, 200)
        eq_(data['description'], new_description)

    def test_update_invalid_app(self):
        self.feed_permission()
        res, data = self.update(self.client, app=1)
        eq_(res.status_code, 400)
        ok_('app' in data)

    def test_update_no_app(self):
        """
        Skip may be removed when we upgrade to a release that incorporates the
        fix to django-rest-framework issue #1158:

        https://github.com/tomchristie/django-rest-framework/issues/1158
        https://github.com/tomchristie/django-rest-framework/pull/1272
        """
        raise SkipTest('Fails due to bug in django-rest-framework 2.3.9.')
        self.feed_permission()
        res, data = self.update(self.client, app=None)
        eq_(res.status_code, 400)
        ok_('app' in data)


class TestFeedAppViewSetDelete(BaseTestFeedAppViewSet):
    """
    Tests the handling of DELETE requests to detail endpoints of FeedAppViewSet.
    """
    def setUp(self):
        super(TestFeedAppViewSetDelete, self).setUp()
        self.feedapp = self.create_feedapps(1)[0]
        self.url = reverse('feedapp-detail', kwargs={'pk': self.feedapp.pk})

    def delete(self, client, **kwargs):
        res = client.delete(self.url)
        data = json.loads(res.content) if res.content else ''
        return res, data

    def test_delete_anonymous(self):
        res, data = self.delete(self.anon)
        eq_(res.status_code, 403)

    def test_delete_no_permission(self):
        res, data = self.delete(self.client)
        eq_(res.status_code, 403)

    def test_delete_with_permission(self):
        self.feed_permission()
        res, data = self.delete(self.client)
        eq_(res.status_code, 204)
