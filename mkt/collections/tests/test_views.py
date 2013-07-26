import json

from django.core.urlresolvers import reverse

from nose.tools import eq_

import amo.tests
from mkt.api.tests.test_oauth import RestOAuth
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.site.fixtures import fixture


class TestCollectionViewSet(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.create_switch('rocketfuel')
        super(TestCollectionViewSet, self).setUp()
        self.serializer = CollectionSerializer()
        self.collection_data = {
            'name': 'My Favorite Games',
            'description': 'A collection of my favorite games'
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.list_url = reverse('collections-list')

    def listing(self, client):
        for app in self.apps:
            self.collection.add_app(app)
        res = client.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['objects'][0]['apps'], self.collection.app_urls())

    def test_listing(self):
        self.listing(self.anon)

    def test_listing_no_perms(self):
        self.listing(self.client)

    def test_listing_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        self.listing(self.client)

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
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.create(self.client)
        eq_(res.status_code, 201)

    def add_app(self, client):
        url = reverse('collections-add-app', kwargs={'pk': self.collection.pk})
        res = client.post(url, json.dumps({'app': self.apps[0].pk}))
        data = json.loads(res.content)
        return res, data

    def test_add_app_anon(self):
        res, data = self.add_app(self.anon)
        eq_(res.status_code, 403)

    def test_add_app_no_perms(self):
        res, data = self.add_app(self.client)
        eq_(res.status_code, 403)

    def test_add_app_has_perms(self):
        self.grant_permission(self.profile, 'Apps:Publisher')
        res, data = self.add_app(self.client)
        eq_(res.status_code, 201)
