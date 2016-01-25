from django.core.cache import cache
from django.test.utils import override_settings

import mock
from jingo.helpers import datetime as datetime_filter
from pyquery import PyQuery as pq
from tower import strip_whitespace

import amo
import amo.tests
from amo.tests import addon_factory
from amo.urlresolvers import reverse
from addons.models import (Addon, AddonDependency, CompatOverride,
                           CompatOverrideRange, Preview)
from bandwagon.models import MonthlyPick
from discovery import views
from discovery.forms import DiscoveryModuleForm
from discovery.models import DiscoveryModule
from discovery.modules import registry


class TestModuleAdmin(amo.tests.TestCase):

    def test_sync_db_and_registry(self):
        def check():
            views._sync_db_and_registry(qs, 1)
            assert qs.count() == len(registry)
            modules = qs.values_list('module', flat=True)
            assert set(modules) == set(registry.keys())

        qs = DiscoveryModule.objects.no_cache().filter(app=1)
        assert qs.count() == 0

        # All our modules get added.
        check()

        # The deleted module is removed.
        with mock.patch.dict(registry):
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
        cleaned_locales = form.cleaned_data['locales'].split()
        assert sorted(cleaned_locales) == ['en-US', 'fa', 'he']


class TestUrls(amo.tests.TestCase):
    fixtures = ['base/users', 'base/featured', 'addons/featured',
                'base/addon_3615']

    def test_reverse(self):
        assert '/en-US/firefox/discovery/pane/10.0/WINNT' == reverse('discovery.pane', kwargs=dict(version='10.0', platform='WINNT'))
        assert '/en-US/firefox/discovery/pane/10.0/WINNT/strict' == reverse('discovery.pane', args=('10.0', 'WINNT', 'strict'))

    def test_resolve_addon_view(self):
        r = self.client.get('/en-US/firefox/discovery/addon/3615', follow=True)
        url = reverse('discovery.addons.detail', args=['a3615'])
        self.assert3xx(r, url, 301)

    def test_resolve_disco_pane(self):
        # Redirect to default 'strict' if version < 10.
        r = self.client.get('/en-US/firefox/discovery/4.0/Darwin', follow=True)
        url = reverse('discovery.pane', args=['4.0', 'Darwin', 'strict'])
        self.assert3xx(r, url, 302)

        # Redirect to default 'ignore' if version >= 10.
        r = self.client.get('/en-US/firefox/discovery/10.0/Darwin',
                            follow=True)
        url = reverse('discovery.pane', args=['10.0', 'Darwin', 'ignore'])
        self.assert3xx(r, url, 302)

    def test_no_compat_mode(self):
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT')
        assert r.status_code == 200

    def test_with_compat_mode(self):
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/strict')
        assert r.status_code == 200
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/normal')
        assert r.status_code == 200
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/ignore')
        assert r.status_code == 200
        r = self.client.head('/en-US/firefox/discovery/pane/10.0/WINNT/blargh')
        assert r.status_code == 404


class TestPromos(amo.tests.TestCase):
    fixtures = ['base/users', 'discovery/discoverymodules']

    def get_disco_url(self, platform, version):
        return reverse('discovery.pane.promos', args=[platform, version])

    def get_home_url(self):
        return reverse('addons.homepage_promos')

    def test_no_params(self):
        r = self.client.get(self.get_home_url())
        assert r.status_code == 404

    def test_mac(self):
        # Ensure that we get the same thing for the homepage promos.
        r_mac = self.client.get(self.get_home_url(),
                                {'version': '10.0', 'platform': 'mac'})
        r_darwin = self.client.get(self.get_disco_url('10.0', 'Darwin'))
        assert r_mac.status_code == 200
        assert r_darwin.status_code == 200
        assert r_mac.content == r_darwin.content

    def test_win(self):
        r_win = self.client.get(self.get_home_url(),
                                {'version': '10.0', 'platform': 'win'})
        r_winnt = self.client.get(self.get_disco_url('10.0', 'WINNT'))
        assert r_win.status_code == 200
        assert r_winnt.status_code == 200
        assert r_win.content == r_winnt.content

    def test_hidden(self):
        DiscoveryModule.objects.all().delete()
        r = self.client.get(self.get_disco_url('10.0', 'Darwin'))
        assert r.status_code == 200
        assert r.content == ''


class TestPane(amo.tests.TestCase):
    fixtures = ['addons/featured', 'base/addon_3615', 'base/collections',
                'base/featured', 'base/users',
                'bandwagon/featured_collections']

    def setUp(self):
        super(TestPane, self).setUp()
        self.url = reverse('discovery.pane', args=['3.7a1pre', 'Darwin'])

    def test_my_account(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('discovery.pane.account'))
        assert r.status_code == 200
        doc = pq(r.content)

        s = doc('#my-account')
        assert s
        a = s.find('a').eq(0)
        assert a.attr('href') == reverse('users.profile', args=['regularuser'])
        assert a.text() == 'My Profile'

        a = s.find('a').eq(1)
        assert a.attr('href') == reverse('collections.detail', args=['regularuser', 'favorites'])
        assert a.text() == 'My Favorites'

        a = s.find('a').eq(2)
        assert a.attr('href') == reverse('collections.user', args=['regularuser'])
        assert a.text() == 'My Collections'

    def test_mission(self):
        r = self.client.get(reverse('discovery.pane.account'))
        assert pq(r.content)('#mission')

    def test_featured_addons_section(self):
        r = self.client.get(self.url)
        assert pq(r.content)('#featured-addons h2').text() == 'Featured Add-ons'

    def test_featured_addons(self):
        r = self.client.get(self.url)
        p = pq(r.content)('#featured-addons')

        addon = Addon.objects.get(id=7661)
        li = p.find('li[data-guid="%s"]' % addon.guid)
        a = li.find('a.addon-title')
        url = reverse('discovery.addons.detail', args=[7661])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        assert li.find('h3').text() == unicode(addon.name)
        assert li.find('img').attr('src') == addon.icon_url

        addon = Addon.objects.get(id=2464)
        li = p.find('li[data-guid="%s"]' % addon.guid)
        assert li.attr('data-guid') == addon.guid
        a = li.find('a.addon-title')
        url = reverse('discovery.addons.detail', args=[2464])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        assert li.find('h3').text() == unicode(addon.name)
        assert li.find('img').attr('src') == addon.icon_url

    def test_featured_personas_section(self):
        r = self.client.get(self.url)
        h2 = pq(r.content)('#featured-themes h2')
        assert h2.text() == 'See all Featured Themes'
        assert h2.find('a.all').attr('href') == reverse('browse.personas')

    @override_settings(MEDIA_URL='/media/', STATIC_URL='/static/')
    def test_featured_personas(self):
        addon = Addon.objects.get(id=15679)
        r = self.client.get(self.url)
        doc = pq(r.content)

        featured = doc('#featured-themes')
        assert featured.length == 1

        # Look for all images that are not icon uploads.
        imgs = doc('img:not([src*="/media/"])')
        imgs_ok = (pq(img).attr('src').startswith('/static/')
                   for img in imgs)
        assert all(imgs_ok), 'Images must be prefixed with MEDIA_URL!'

        featured = doc('#featured-themes')
        assert featured.length == 1

        a = featured.find('a[data-browsertheme]')
        url = reverse('discovery.addons.detail', args=[15679])
        assert a.attr('href').endswith(url + '?src=discovery-featured'), (
            'Unexpected add-on details URL')
        assert a.attr('target') == '_self'
        assert featured.find('.addon-title').text() == unicode(addon.name)


class TestDetails(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592']

    def setUp(self):
        super(TestDetails, self).setUp()
        self.addon = self.get_addon()
        self.detail_url = reverse('discovery.addons.detail',
                                  args=[self.addon.slug])
        self.eula_url = reverse('discovery.addons.eula',
                                args=[self.addon.slug])

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def test_no_restart(self):
        f = self.addon.current_version.all_files[0]
        assert f.no_restart is False
        r = self.client.get(self.detail_url)
        assert pq(r.content)('#no-restart').length == 0
        f.update(no_restart=True)
        r = self.client.get(self.detail_url)
        assert pq(r.content)('#no-restart').length == 1

    def test_install_button_eula(self):
        doc = pq(self.client.get(self.detail_url).content)
        assert doc('#install .install-button').text() == 'Download Now'
        assert doc('#install .eula').text() == 'View End-User License Agreement'
        doc = pq(self.client.get(self.eula_url).content)
        assert doc('#install .install-button').text() == 'Download Now'

    def test_install_button_no_eula(self):
        self.addon.update(eula=None)
        doc = pq(self.client.get(self.detail_url).content)
        assert doc('#install .install-button').text() == 'Download Now'
        r = self.client.get(self.eula_url)
        self.assert3xx(r, self.detail_url, 302)

    def test_dependencies(self):
        doc = pq(self.client.get(self.detail_url).content)
        assert doc('.dependencies').length == 0
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        assert self.addon.all_dependencies == [req]
        cache.clear()
        d = pq(self.client.get(self.detail_url).content)('.dependencies')
        assert d.length == 1
        a = d.find('ul a')
        assert a.text() == unicode(req.name)
        assert a.attr('href').endswith('?src=discovery-dependencies') is True


class TestPersonaDetails(amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/users']

    def setUp(self):
        super(TestPersonaDetails, self).setUp()
        self.addon = Addon.objects.get(id=15663)
        self.url = reverse('discovery.addons.detail', args=[self.addon.slug])

    def test_page(self):
        r = self.client.get(self.url)
        assert r.status_code == 200

    def test_by(self):
        """Test that the `by ... <authors>` section works."""
        r = self.client.get(self.url)
        assert pq(r.content)('h2.author').text().startswith(
            'by persona_author')

    def test_no_version(self):
        """Don't display a version number for themes."""
        r = self.client.get(self.url)
        assert pq(r.content)('h1 .version') == []

    def test_created_not_updated(self):
        """Don't display the updated date but the created date for themes."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        details = doc('.addon-info li')

        # There's no "Last Updated" entry.
        assert not any('Last Updated' in node.text_content()
                       for node in details)

        # But there's a "Created" entry.
        for detail in details:
            if detail.find('h3').text_content() == 'Created':
                created = detail.find('p').text_content()
                assert created == strip_whitespace(datetime_filter(self.addon.created))
                break  # Needed, or we go in the "else" clause.
        else:
            assert False, 'No "Created" entry found.'


class TestDownloadSources(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users',
                'base/collections', 'base/featured', 'addons/featured',
                'discovery/discoverymodules']

    def setUp(self):
        super(TestDownloadSources, self).setUp()
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
    fixtures = ['base/users', 'base/addon_3615',
                'discovery/discoverymodules']

    def setUp(self):
        super(TestMonthlyPick, self).setUp()
        self.url = reverse('discovery.pane.promos', args=['Darwin', '10.0'])
        self.addon = Addon.objects.get(id=3615)
        DiscoveryModule.objects.create(
            app=amo.FIREFOX.id, ordering=4,
            module='Monthly Pick')

    def test_monthlypick(self):
        mp = MonthlyPick.objects.create(addon=self.addon, blurb='BOOP',
                                        image='http://mozilla.com')
        r = self.client.get(self.url)
        assert r.content == ''
        mp.update(locale='')

        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        assert pick.length == 1
        assert pick.parents('.panel').attr('data-addonguid') == self.addon.guid
        a = pick.find('h3 a')
        url = reverse('discovery.addons.detail', args=['a3615'])
        assert a.attr('href').endswith(url + '?src=discovery-promo'), (
            'Unexpected add-on details URL: %s' % url)
        assert a.attr('target') == '_self'
        assert a.text() == unicode(self.addon.name)
        assert pick.find('img').attr('src') == 'http://mozilla.com'
        assert pick.find('.wrap > div > div > p').text() == 'BOOP'
        assert pick.find('p.install-button a').attr('href') .endswith('?src=discovery-promo') is True

    def test_monthlypick_no_image(self):
        MonthlyPick.objects.create(addon=self.addon, blurb='BOOP', locale='',
                                   image='')

        # Tests for no image when screenshot not set.
        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        assert pick.length == 1
        assert pick.find('img').length == 0

        # Tests for screenshot image when set.
        Preview.objects.create(addon=self.addon)
        r = self.client.get(self.url)
        pick = pq(r.content)('#monthly')
        assert pick.length == 1
        assert pick.find('img').attr('src') == self.addon.all_previews[0].image_url

    def test_no_monthlypick(self):
        r = self.client.get(self.url)
        assert r.content == ''


class TestPaneMoreAddons(amo.tests.TestCase):
    fixtures = ['base/appversion']

    def setUp(self):
        super(TestPaneMoreAddons, self).setUp()
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
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 2

    def test_hotness_strict_filtered(self):
        # Defaults to strict compat mode, one is within range.
        res = self.client.get(self._url(version='6.0'))
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 1
        self.assertContains(res, self.addon2.name)

    def test_hotness_ignore(self):
        # Defaults to ignore compat mode for Fx v10, both are compatible.
        res = self.client.get(self._url(version='10.0'))
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 2

    def test_hotness_normal_strict_opt_in(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon_factory(hotness=50, version_kw=dict(max_app_version='7.0'),
                      file_kw=dict(strict_compatibility=True))

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 2

    def test_hotness_normal_binary_components(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon_factory(hotness=50, version_kw=dict(max_app_version='7.0'),
                      file_kw=dict(binary_components=True))

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 2

    def test_hotness_normal_compat_override(self):
        # Add a 3rd add-on that should get filtered out b/c of compatibility.
        addon3 = addon_factory(hotness=50,
                               version_kw=dict(max_app_version='7.0'))

        # Add override for this add-on.
        compat = CompatOverride.objects.create(guid='three', addon=addon3)
        CompatOverrideRange.objects.create(
            compat=compat, app=1,
            min_version=addon3.current_version.version, max_version='*')

        res = self.client.get(self._url(version='12.0', compat_mode='normal'))
        assert res.status_code == 200
        assert pq(res.content)('.featured-addons').length == 2
