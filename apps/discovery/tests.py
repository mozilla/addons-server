import json

from django import test

import mock
from nose.tools import eq_
import test_utils

import amo
from amo.urlresolvers import reverse
from applications.models import Application
from bandwagon.models import Collection, SyncedCollection, CollectionToken
from discovery import views
from discovery.forms import DiscoveryModuleForm
from discovery.models import DiscoveryModule
from discovery.modules import registry


class RecsTest(test_utils.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/addon-recs',
                'base/addon_5299_gcal', 'base/category', 'base/featured']

    @classmethod
    def setup_class(cls):
        test.Client().get('/')

    def setUp(self):
        self.url = reverse('discovery.recs')
        self.guids = ('bettergcal@ginatrapani.org',
                      'foxyproxy@eric.h.jung',
                      'isreaditlater@ideashower.com',
                      'not-a-real-guid',)
        self.ids = [5299, 2464, 7661]
        self.json = json.dumps({'guids': self.guids})
        # Found in bandwagon.TestRecommendations.expected_recs.
        self.expected_recs = [6249, 7661, 6665, 4781, 6366]

    def test_get(self):
        """GET should find method not allowed."""
        response = self.client.get(self.url)
        eq_(response.status_code, 405)

    def test_empty_post_data(self):
        response = self.client.post(self.url)
        eq_(response.status_code, 400)

    def test_bad_post_data(self):
        response = self.client.post(self.url, '{]{',
                                    content_type='application/json')
        eq_(response.status_code, 400)

    def test_no_guids(self):
        response = self.client.post(self.url, '{}',
                                    content_type='application/json')
        eq_(response.status_code, 400)

    def test_get_addon_ids(self):
        ids = set(views.get_addon_ids(self.guids))
        eq_(ids, set(self.ids))

    def test_get_synced_collection(self):
        # Get a fresh synced collection.
        c = views.get_synced_collection(self.ids, 'token')
        eq_(c.listed, False)
        eq_(c.type, amo.COLLECTION_SYNCHRONIZED)
        eq_(set(c.addons.values_list('id', flat=True)), set(self.ids))

        # Check that the token was set.
        eq_(c.token_set.get().token, 'token')

        # Make sure we get the same collection if we try again.
        next = views.get_synced_collection(self.ids, 'next')
        eq_(next.id, c.id)
        eq_(set(next.addons.values_list('id', flat=True)), set(self.ids))
        eq_(list(c.token_set.values_list('token', flat=True)),
            ['token', 'next'])

    def test_get_synced_collection_with_dupes(self):
        """It shouldn't happen, but make sure we handled synced dupes."""
        one = SyncedCollection.objects.create()
        one.set_addons(self.ids)
        two = SyncedCollection.objects.create()
        two.set_addons(self.ids)

        three = views.get_synced_collection(self.ids, 'token')
        assert one.addon_index == two.addon_index == three.addon_index

    @mock.patch('discovery.views.uuid.uuid4')
    def test_get_random_token(self, uuid_mock):
        uuid_mock.side_effect = ['two', 'one', 'one', 'one'].pop
        eq_(views.get_random_token(), 'one')
        views.get_synced_collection([], 'one')
        eq_(views.get_random_token(), 'two')

    def test_success(self):
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)

        eq_(set(data.keys()), set(['token', 'recommendations', 'addons']))
        eq_(len(data['addons']), 5)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, self.expected_recs)

        # Our token should match a synced collection, and that collection's
        # recommendations should match what we got.
        q = SyncedCollection.objects.filter(token_set__token=data['token'])
        eq_(len(q), 1)
        eq_(q[0].recommended_collection.get_url_path(),
            data['recommendations'])

    def test_recs_bad_token(self):
        post_data = json.dumps(dict(guids=self.guids, token='fake'))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        data = json.loads(response.content)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, self.expected_recs)

    def test_update_same_index(self):
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        one = json.loads(response.content)

        post_data = json.dumps(dict(guids=self.guids, token=one['token']))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        two = json.loads(response.content)

        # We sent our existing token and the same ids, so the
        # responses should be identical.
        eq_(one, two)

        eq_(CollectionToken.objects.count(), 1)

    def test_update_new_index(self):
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        one = json.loads(response.content)

        post_data = json.dumps(dict(guids=self.guids[:1], token=one['token']))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        two = json.loads(response.content)

        eq_(one['token'], two['token'])
        assert one['recommendations'] != two['recommendations']
        assert one['addons'] != two['addons']
        eq_(CollectionToken.objects.count(), 1)
        eq_(len(Collection.objects.filter(type=amo.COLLECTION_SYNCHRONIZED)),
            2)


class TestModuleAdmin(test_utils.TestCase):
    fixtures = ('base/apps', )

    def test_sync_db_and_registry(self):
        def check():
            views._sync_db_and_registry(qs, app)
            eq_(qs.count(), len(registry))
            modules = qs.values_list('module', flat=True)
            eq_(set(modules), set(registry.keys()))

        app = Application.objects.create()
        qs = DiscoveryModule.uncached.filter(app=app)
        eq_(qs.count(), 0)

        # All our modules get added.
        check()

        # The deleted module is removed.
        registry.popitem()
        check()

    def test_discovery_module_form_bad_locale(self):
        d = dict(app=1, module='xx', locales='fake')
        form = DiscoveryModuleForm(d)
        assert form.errors['locales']


    def test_discovery_module_form_dedupe(self):
        d = dict(app=amo.FIREFOX.id, module='xx', locales='en-US he he fa fa')
        form = DiscoveryModuleForm(d)
        assert form.is_valid()
        eq_(form.cleaned_data['locales'], 'fa en-US he')
