import json

from django import test
from django.core.cache import cache

from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.tests import addon_factory
import addons.signals
from amo.urlresolvers import reverse
from addons.models import (Addon, AddonDependency, AddonUpsell, CompatOverride,
                           CompatOverrideRange, Preview)
from applications.models import Application, AppVersion
from bandwagon.models import MonthlyPick, SyncedCollection
from bandwagon.tests.test_models import TestRecommendations as Recs
from discovery import views
from discovery.forms import DiscoveryModuleForm
from discovery.models import DiscoveryModule
from discovery.modules import registry
from files.models import File
from versions.models import Version, ApplicationsVersions


class TestRecs(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/addon_3615',
                'base/addon-recs', 'base/addon_5299_gcal', 'base/category',
                'base/featured', 'addons/featured']

    @classmethod
    def setUpClass(cls):
        super(TestRecs, cls).setUpClass()
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

        self.min_id, self.max_id = 1, 364  # see test_min_max_appversion
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

    def test_success(self):
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)

        eq_(set(data.keys()), set(['token2', 'addons']))
        eq_(len(data['addons']), 9)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, self.expected_recs)

    def test_only_show_public(self):
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

    def test_app_support_filter(self):
        # The fixture doesn't contain valid add-ons for the provided URL args.
        url = reverse('discovery.recs', args=['5.0', 'Darwin'])
        response = self.client.post(url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)
        eq_(len(data['addons']), 0)

    def test_app_support_filter_ignore(self):
        # The fixture doesn't contain valid add-ons for the provided URL
        # args, but with compat_mode=ignore, it should still find them.
        url = reverse('discovery.recs', args=['5.0', 'Darwin', 'ignore'])
        response = self.client.post(url, self.json,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        eq_(response['Content-type'], 'application/json')
        data = json.loads(response.content)
        eq_(len(data['addons']), 9)
        ids = [a['id'] for a in data['addons']]
        eq_(ids, self.expected_recs)

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

        post_data = json.dumps(dict(guids=self.guids, token2=one['token2']))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        two = json.loads(response.content)

        # We sent our existing token and the same ids, so the
        # responses should be identical.
        eq_(one, two)

    def test_update_new_index(self):
        waffle.models.Sample.objects.create(
            name='disco-pane-store-collections', percent='100.0')
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        one = json.loads(response.content)

        post_data = json.dumps(dict(guids=self.guids[:1],
                                    token2=one['token2']))
        response = self.client.post(self.url, post_data,
                                    content_type='application/json')
        eq_(response.status_code, 200)
        two = json.loads(response.content)

        # Tokens are based on guid list, so these should be different.
        assert one['token2'] != two['token2']
        assert one['addons'] != two['addons']
        eq_(SyncedCollection.objects.filter(addon_index=one['token2']).count(),
            1)
        eq_(SyncedCollection.objects.filter(addon_index=two['token2']).count(),
            1)


class TestModuleAdmin(amo.tests.TestCase):
    fixtures = ['base/apps']

    def test_sync_db_and_registry(self):
        def check():
            views._sync_db_and_registry(qs, app)
            eq_(qs.count(), len(registry))
            modules = qs.values_list('module', flat=True)
            eq_(set(modules), set(registry.keys()))

        app = Application.objects.create()
        qs = DiscoveryModule.objects.no_cache().filter(app=app)
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


class TestUrls(amo.tests.TestCase):
    fixtures = ['base/users', 'base/apps', 'base/featured', 'addons/featured',
                'base/addon_3615']

    def test_reverse(self):
        eq_('/en-US/firefox/discovery/pane/10.0/WINNT',
            reverse('discovery.pane', kwargs=dict(version='10.0',
                                                  platform='WINNT')))
        eq_('/en-US/firefox/discovery/pane/10.0/WINNT/strict',
            reverse('discovery.pane', args=('10.0', 'WINNT', 'strict')))

    def test_resolve_addon_view(self):
        r = self.client.get('/en-US/firefox/discovery/addon/3615', follow=True)
        url = reverse('discovery.addons.detail', args=['a3615'])
        self.assertRedirects(r, url, 301)

    def test_resolve_disco_pane(self):
        # Redirect to default 'strict' if version < 10.
        r = self.client.get('/en-US/firefox/discovery/4.0/Darwin', follow=True)
        url = reverse('discovery.pane', args=['4.0', 'Darwin', 'strict'])
        self.assertRedirects(r, url, 302)

        # Redirect to default 'ignore' if version >= 10.
        r = self.client.get('/en-US/firefox/discovery/10.0/Darwin',
                            follow=True)
        url = reverse('discovery.pane', args=['10.0', 'Darwin', 'ignore'])
        self.assertRedirects(r, url, 302)

    def test_no_compat_mode(self):
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT')
        eq_(r.status_code, 200)

    def test_with_compat_mode(self):
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/strict')
        eq_(r.status_code, 200)
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/normal')
        eq_(r.status_code, 200)
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/ignore')
        eq_(r.status_code, 200)
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/blargh')
        eq_(r.status_code, 404)


class TestPromos(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'discovery/discoverymodules']

    def get_disco_url(self, platform, version):
        return reverse('discovery.pane.promos', args=[platform, version])

    def get_home_url(self):
        return reverse('addons.homepage_promos')

    def test_no_params(self):
        r = self.client.get(self.get_home_url())
        eq_(r.status_code, 404)

    def test_mac(self):
        # Ensure that we get the same thing for the homepage promos.
        r_mac = self.client.get(self.get_home_url(),
                                {'version': '10.0', 'platform': 'mac'})
        r_darwin = self.client.get(self.get_disco_url('10.0', 'Darwin'))
        eq_(r_mac.status_code, 200)
        eq_(r_darwin.status_code, 200)
        eq_(r_mac.content, r_darwin.content)

    def test_win(self):
        r_win = self.client.get(self.get_home_url(),
                                {'version': '10.0', 'platform': 'win'})
        r_winnt = self.client.get(self.get_disco_url('10.0', 'WINNT'))
        eq_(r_win.status_code, 200)
        eq_(r_winnt.status_code, 200)
        eq_(r_win.content, r_winnt.content)

    def test_hidden(self):
        DiscoveryModule.objects.all().delete()
        r = self.client.get(self.get_disco_url('10.0', 'Darwin'))
        eq_(r.status_code, 200)
        eq_(r.content, '')


class TestPane(amo.tests.TestCase):
    fixtures = ['addons/featured', 'base/addon_3615', 'base/apps',
                'base/collections', 'base/featured', 'base/users',
                'bandwagon/featured_collections']

    def setUp(self):
        self.url = reverse('discovery.pane', args=['3.7a1pre', 'Darwin'])

    def test_my_account(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('discovery.pane.account'))
        eq_(r.status_code, 200)
        doc = pq(r.content)

        s = doc('#my-account')
        assert s
        a = s.find('a').eq(0)
        eq_(a.attr('href'), reverse('users.profile', args=['regularuser']))
        eq_(a.text(), 'My Profile')

        a = s.find('a').eq(1)
        eq_(a.attr('href'), reverse('collections.detail',
                                    args=['regularuser', 'favorites']))
        eq_(a.text(), 'My Favorites')

        a = s.find('a').eq(2)
        eq_(a.attr('href'), reverse('collections.user', args=['regularuser']))
        eq_(a.text(), 'My Collections')

    def test_mission(self):
        r = self.client.get(reverse('discovery.pane.account'))
        assert pq(r.content)('#mission')

    def test_featured_addons_section(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#featured-addons h2').text(), 'Featured Add-ons')

    def test_featured_addons(self):
        r = self.client.get(self.url)
        p = pq(r.content)('#featured-addons')

        addon = Addon.objects.get(id=7661)
        li = p.find('li[data-guid="%s"]' % addon.guid)
        a = li.find('a.addon-title')
        url = reverse('discovery.addons.detail', args=[7661])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        eq_(li.find('h3').text(), unicode(addon.name))
        eq_(li.find('img').attr('src'), addon.icon_url)

        addon = Addon.objects.get(id=2464)
        li = p.find('li[data-guid="%s"]' % addon.guid)
        eq_(li.attr('data-guid'), addon.guid)
        a = li.find('a.addon-title')
        url = reverse('discovery.addons.detail', args=[2464])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        eq_(li.find('h3').text(), unicode(addon.name))
        eq_(li.find('img').attr('src'), addon.icon_url)

    def test_featured_personas_section(self):
        r = self.client.get(self.url)
        h2 = pq(r.content)('#featured-themes h2')
        eq_(h2.text(), 'See all Featured Themes')
        eq_(h2.find('a.all').attr('href'), reverse('browse.personas'))

    def test_featured_personas(self):
        addon = Addon.objects.get(id=15679)
        r = self.client.get(self.url)
        doc = pq(r.content)

        featured = doc('#featured-themes')
        eq_(featured.length, 1)

        # Look for all images that are not icon uploads.
        imgs = doc('img:not([src*="/uploads/"])')
        imgs_ok = (pq(img).attr('src').startswith('/media/img/')
                   for img in imgs)
        assert all(imgs_ok), 'Images must be prefixed with MEDIA_URL!'

        featured = doc('#featured-themes')
        eq_(featured.length, 1)

        a = featured.find('a[data-browsertheme]')
        url = reverse('discovery.addons.detail', args=[15679])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        eq_(a.attr('target'), '_self')
        eq_(featured.find('.addon-title').text(), unicode(addon.name))


class TestDetails(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592']

    def setUp(self):
        self.addon = self.get_addon()
        self.detail_url = reverse('discovery.addons.detail',
                                  args=[self.addon.slug])
        self.eula_url = reverse('discovery.addons.eula',
                                 args=[self.addon.slug])

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def test_no_restart(self):
        f = self.addon.current_version.all_files[0]
        eq_(f.no_restart, False)
        r = self.client.get(self.detail_url)
        eq_(pq(r.content)('#no-restart').length, 0)
        f.update(no_restart=True)
        r = self.client.get(self.detail_url)
        eq_(pq(r.content)('#no-restart').length, 1)

    def test_install_button_eula(self):
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('#install .install-button').text(), 'Download Now')
        eq_(doc('#install .eula').text(), 'View End-User License Agreement')
        doc = pq(self.client.get(self.eula_url).content)
        eq_(doc('#install .install-button').text(), 'Download Now')

    def test_install_button_no_eula(self):
        self.addon.update(eula=None)
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('#install .install-button').text(), 'Download Now')
        r = self.client.get(self.eula_url)
        self.assertRedirects(r, self.detail_url, 302)

    def test_perf_warning(self):
        eq_(self.addon.ts_slowness, None)
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('.performance-note').length, 0)
        self.addon.update(ts_slowness=100)
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('.performance-note').length, 1)

    def test_dependencies(self):
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('.dependencies').length, 0)
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        eq_(self.addon.all_dependencies, [req])
        cache.clear()
        d = pq(self.client.get(self.detail_url).content)('.dependencies')
        eq_(d.length, 1)
        a = d.find('ul a')
        eq_(a.text(), unicode(req.name))
        eq_(a.attr('href').endswith('?src=discovery-dependencies'), True)

    def test_upsell(self):
        doc = pq(self.client.get(self.detail_url).content)
        eq_(doc('.upsell').length, 0)
        premie = Addon.objects.get(id=592)
        AddonUpsell.objects.create(free=self.addon, premium=premie)
        upsell = pq(self.client.get(self.detail_url).content)('.upsell')
        eq_(upsell.length, 1)
        a = upsell.find('.premium a')
        eq_(a.text(), unicode(premie.name))
        eq_(a.attr('href').endswith('?src=discovery-upsell'), True)


class TestPersonaDetails(amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.persona.author = self.persona.author
        self.persona.save()
        self.url = reverse('discovery.addons.detail', args=[self.addon.slug])

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_by(self):
        """Test that the `by ... <authors>` section works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h2.author').text().startswith('by persona_author')


class TestDownloadSources(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/users',
                'base/collections', 'base/featured', 'addons/featured',
                'discovery/discoverymodules']

    def setUp(self):
        self.url = reverse('discovery.pane', args=['3.7a1pre', 'Darwin'])

    def test_detail(self):
        url = reverse('discovery.addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('#install a.download').attr('href').endswith(
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
        assert doc('#install a.download').attr('href').endswith(
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


class TestMonthlyPick(amo.tests.TestCase):
    fixtures = ['base/users', 'base/apps', 'base/addon_3615',
                'discovery/discoverymodules']

    def setUp(self):
        self.url = reverse('discovery.pane.promos', args=['Darwin', '10.0'])
        self.addon = Addon.objects.get(id=3615)
        DiscoveryModule.objects.create(
            app=Application.objects.get(id=amo.FIREFOX.id), ordering=4,
            module='Monthly Pick')

    def test_monthlypick(self):
        mp = MonthlyPick.objects.create(addon=self.addon, blurb='BOOP',
                                        image='http://mozilla.com')
        r = self.client.get(self.url)
        eq_(r.content, '')
        mp.update(locale='')

        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        eq_(pick.length, 1)
        eq_(pick.parents('.panel').attr('data-addonguid'), self.addon.guid)
        a = pick.find('h3 a')
        url = reverse('discovery.addons.detail', args=['a3615'])
        assert a.attr('href').endswith(url + '?src=discovery-promo'), (
            'Unexpected add-on details URL: %s' % url)
        eq_(a.attr('target'), '_self')
        eq_(a.text(), unicode(self.addon.name))
        eq_(pick.find('img').attr('src'), 'http://mozilla.com')
        eq_(pick.find('.wrap > div > div > p').text(), 'BOOP')
        eq_(pick.find('p.install-button a').attr('href')
                .endswith('?src=discovery-promo'), True)

    def test_monthlypick_no_image(self):
        MonthlyPick.objects.create(addon=self.addon, blurb='BOOP', locale='',
                                   image='')

        # Tests for no image when screenshot not set.
        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        eq_(pick.length, 1)
        eq_(pick.find('img').length, 0)

        # Tests for screenshot image when set.
        Preview.objects.create(addon=self.addon)
        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        eq_(pick.length, 1)
        eq_(pick.find('img').attr('src'), self.addon.all_previews[0].image_url)

    def test_no_monthlypick(self):
        r = self.client.get(self.url)
        eq_(r.content, '')


class TestPaneMoreAddons(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/appversion']

    def setUp(self):
        self.addon1 = addon_factory(hotness=99,
                                    version_kw=dict(max_app_version='5.0'))
        self.addon2 = addon_factory(hotness=0,
                                    version_kw=dict(max_app_version='6.0'))

    def _url(self, **kwargs):
        default = dict(
            section='up-and-coming',
            version='5.0',
            platform='Darwin')
        default.update(kwargs)
        return reverse('discovery.pane.more_addons', kwargs=default)

    def test_hotness_strict(self):
        # Defaults to strict compat mode, both are within range.
        res = self.client.get(self._url())
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 2)

    def test_hotness_strict_filtered(self):
        # Defaults to strict compat mode, one is within range.
        res = self.client.get(self._url(version='6.0'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 1)
        self.assertContains(res, self.addon2.name)

    def test_hotness_ignore(self):
        # Defaults to ignore compat mode for Fx v10, both are compatible.
        res = self.client.get(self._url(version='10.0'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 2)

    def test_hotness_normal_strict_opt_in(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon_factory(hotness=50, version_kw=dict(max_app_version='7.0'),
                      file_kw=dict(strict_compatibility=True))

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 2)

    def test_hotness_normal_binary_components(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon_factory(hotness=50, version_kw=dict(max_app_version='7.0'),
                      file_kw=dict(binary_components=True))

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 2)

    def test_hotness_normal_compat_override(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon3 = addon_factory(hotness=50,
                               version_kw=dict(max_app_version='7.0'))

        # Add override for this add-on.
        compat = CompatOverride.objects.create(guid='three', addon=addon3)
        CompatOverrideRange.objects.create(
            compat=compat, app=Application.objects.get(pk=1),
            min_version=addon3.current_version.version, max_version='*')

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('.featured-addons').length, 2)
