import json

from django import test

import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
import addons.signals
from amo.urlresolvers import reverse
from addons.models import Addon
from applications.models import Application, AppVersion
from bandwagon.models import Collection, SyncedCollection, CollectionToken
from bandwagon.tests.test_models import TestRecommendations as Recs
from discovery import views
from discovery.forms import DiscoveryModuleForm
from discovery.models import DiscoveryModule
from discovery.modules import registry
from files.models import File
from versions.models import Version, ApplicationsVersions


class TestRecs(test_utils.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/addon-recs',
                'base/addon_5299_gcal', 'base/category', 'base/featured']

    @classmethod
    def setup_class(cls):
        test.Client().get('/')

    def setUp(self):
        self.url = reverse('discovery.recs', args=['3.6', 'Darwin'])
        self.guids = ('bettergcal@ginatrapani.org',
                      'foxyproxy@eric.h.jung',
                      'isreaditlater@ideashower.com',
                      'not-a-real-guid',)
        self.ids = Recs.ids
        self.guids = [a.guid or 'bad-guid'
                      for a in Addon.objects.filter(id__in=self.ids)]
        self.json = json.dumps({'guids': self.guids})
        # The view is limited to returning 9 add-ons.
        self.expected_recs = Recs.expected_recs()[:9]

        self.min_id, self.max_id = 1, 313  # see test_min_max_appversion
        for addon in Addon.objects.all():
            v = Version.objects.create(addon=addon)
            File.objects.create(version=v, status=amo.STATUS_PUBLIC)
            ApplicationsVersions.objects.create(
                version=v, application_id=amo.FIREFOX.id,
                min_id=self.min_id, max_id=self.max_id)
            addon.update(_current_version=v)
            addons.signals.version_changed.send(sender=addon)
        Addon.objects.update(status=amo.STATUS_PUBLIC, disabled_by_user=False)

    def test_min_max_appversion(self):
        # These version numbers are hardcoded for speed, make sure the
        # assumption is correct.
        versions = AppVersion.objects.filter(application=amo.FIREFOX.id)
        min_ = versions.order_by('version_int')[0]
        max_ = versions.order_by('-version_int')[0]
        eq_(self.min_id, min_.id)
        eq_(self.max_id, max_.id)

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

    @mock.patch('api.views')
    def test_success(self, api_mock):
        raise SkipTest()  # bug 640694
        api_mock.addon_filter = lambda xs, _, limit, *args, **kw: xs[:limit]
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)

        eq_(set(data.keys()), set(['token', 'addons']))
        eq_(len(data['addons']), 9)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, self.expected_recs)

        # Our token should match a synced collection, and that collection's
        # recommendations should match what we got.
        q = SyncedCollection.objects.filter(token_set__token=data['token'])
        eq_(len(q), 1)
        eq_(q[0].recommended_collection.get_url_path(),
            data['recommendations'])

    @mock.patch('api.views')
    def test_only_show_public(self, api_mock):
        raise SkipTest()  # bug 640694
        api_mock.addon_filter = lambda xs, _, limit, *args, **kw: xs[:limit]

        # Mark one add-on as non-public.
        unpublic = self.expected_recs[0]
        Addon.objects.filter(id=unpublic).update(status=amo.STATUS_LITE)
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)

        data = json.loads(response.content)
        eq_(len(data['addons']), 9)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, Recs.expected_recs()[1:10])
        assert unpublic not in ids

    def test_filter(self):
        # The fixture doesn't contain valid add-ons so calling addon_filter on
        # the recommendations will return nothing.
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)
        eq_(len(data['addons']), 0)

    @mock.patch('api.views')
    def test_recs_bad_token(self, api_mock):
        raise SkipTest()  # bug 640694
        api_mock.addon_filter = lambda xs, _, limit, *args, **kw: xs[:limit]
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

    @mock.patch('api.views')
    def test_update_new_index(self, api_mock):
        api_mock.addon_filter = lambda xs, _, limit, *args, **kw: xs[:limit]
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        one = json.loads(response.content)

        post_data = json.dumps(dict(guids=self.guids[:1], token=one['token']))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        two = json.loads(response.content)

        eq_(one['token'], two['token'])
        # assert one['recommendations'] != two['recommendations']
        assert one['addons'] != two['addons']
        eq_(CollectionToken.objects.count(), 1)
        eq_(len(Collection.objects.filter(type=amo.COLLECTION_SYNCHRONIZED)),
            2)


class TestModuleAdmin(test_utils.TestCase):
    fixtures = ['base/apps']

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


class TestUrls(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615']

    def test_resolve_addon_view(self):
        r = self.client.get('/en-US/firefox/discovery/addon/3615', follow=True)
        url = reverse('discovery.addons.detail', args=['a3615'])
        self.assertRedirects(r, url, 301)

    def test_resolve_disco_pane(self):
        r = self.client.get('/en-US/firefox/discovery/4.0b8/Darwin',
                            follow=True)
        url = reverse('discovery.pane', args=['4.0b8', 'Darwin'])
        self.assertRedirects(r, url, 301)


class TestPane(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users']

    def setUp(self):
        self.url = reverse('discovery.pane', args=['3.7a1pre', 'Darwin'])

    def test_header_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('header.auth')
        assert doc('#my-account')

    def test_header_logged_out(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('header.auth')
        assert doc('#mission')


class TestDownloadSources(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/collections',
                'base/featured', 'addons/featured',
                'discovery/discoverymodules']

    def setUp(self):
        self.url = reverse('discovery.pane', args=['3.7a1pre', 'Darwin'])

    def test_promo(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        urls = doc('#main-feature .collection a[href$="?src=discovery-promo"]')
        eq_(urls.length, 2)

    def test_featured_addons(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        urls = doc('#featured-addons li a[href$="?src=discovery-featured"]')
        eq_(urls.length, 2)

    def test_featured_personas(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#featured-personas li a').attr('href').endswith(
            '?src=discovery-featured')

    def test_detail(self):
        url = reverse('discovery.addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('#install a.go').attr('href').endswith(
            '?src=discovery-details')
        assert doc('#install li:eq(1)').find('a').attr('href').endswith(
            '?src=discovery-learnmore')
        assert doc('#install li:eq(2)').find('a').attr('href').endswith(
            '?src=discovery-learnmore')

    def test_detail_trickle(self):
        url = (reverse('discovery.addons.detail', args=['a3615']) +
               '?src=discovery-featured')
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('#install a.go').attr('href').endswith(
            '?src=discovery-featured')

    def test_eula(self):
        url = reverse('discovery.addons.eula', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('#install a.download').attr('href').endswith(
            '?src=discovery-details')
        assert doc('#install li:eq(1)').find('a').attr('href').endswith(
            '?src=discovery-details')

    def test_eula_trickle(self):
        url = (reverse('discovery.addons.eula', args=['a3615']) +
               '?src=discovery-upandcoming')
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('#install a.download').attr('href').endswith(
            '?src=discovery-upandcoming')
        assert doc('#install li:eq(1)').find('a').attr('href').endswith(
            '?src=discovery-upandcoming')
