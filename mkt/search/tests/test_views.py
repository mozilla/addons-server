import json

from django.conf import settings

import mock
from nose import SkipTest
from nose.tools import eq_, nottest
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import AddonCategory, AddonDeviceType, Category
from amo.helpers import numberfmt
from amo.urlresolvers import reverse
from amo.utils import urlparams
from search.tests.test_views import TestAjaxSearch
from stats.models import ClientData
from users.models import UserProfile

import mkt
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.webapps.tests.test_views import PaidAppMixin
from mkt.webapps.models import AddonExcludedRegion as AER, Installed, Webapp


class SearchBase(amo.tests.ESTestCase):

    def get_results(self, r, sort=False):
        """Return pks of add-ons shown on search results page."""
        results = [a.id for a in r.context['pager'].object_list]
        if sort:
            results = sorted(results)
        return results

    def check_sort_links(self, key, title=None, sort_by=None, reverse=True,
                         params=None):
        if not params:
            params = {}
        r = self.client.get(urlparams(self.url, sort=key, **params))
        eq_(r.status_code, 200)

        if sort_by:
            results = r.context['pager'].object_list
            expected = sorted(results, key=lambda x: getattr(x, sort_by),
                              reverse=reverse)
            eq_(list(results), expected)

    def check_results(self, params, expected):
        r = self.client.get(urlparams(self.url, **params), follow=True)
        eq_(r.status_code, 200)
        got = self.get_results(r)
        eq_(got, expected,
            'Got: %s. Expected: %s. Parameters: %s' % (got, expected, params))
        return r


class TestWebappSearch(PaidAppMixin, SearchBase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.url = reverse('search.search')

        self.webapp = Webapp.objects.get(id=337141)
        self.apps = [self.webapp]
        self.cat = Category.objects.create(name='Games', type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        # Emit post-save signal so the app gets reindexed.
        self.webapp.save()
        self.refresh()

    def _generate(self, num=3):
        for x in xrange(num):
            app = amo.tests.app_factory()
            AddonCategory.objects.create(addon=app, category=self.cat)
            self.apps.append(app)
        self.refresh()

    @amo.tests.mock_es
    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')

    def test_case_insensitive(self):
        self.refresh()
        self.check_results({'q': 'steam'}, [self.webapp.pk])
        self.check_results({'q': 'Steam'}, [self.webapp.pk])

    def test_results_item(self):
        r = self.client.get(self.url)
        item = pq(r.content)('.listing .item')
        eq_(item.length, 1)
        a = item.find('a')
        eq_(a.find('h3').text(), unicode(self.webapp.name))
        raise SkipTest('until source links are fixed, bug 785990')
        eq_(a.attr('href'),
            urlparams(self.webapp.get_url_path(), src='mkt-search'))

    def check_cat_filter(self, params):
        cat_selected = params.get('cat') == self.cat.id
        r = self.client.get(self.url)
        pager = r.context['pager']

        r = self.client.get(urlparams(self.url, **params))
        eq_(list(r.context['pager'].object_list), list(pager.object_list),
            '%s != %s' % (self.url, urlparams(self.url, **params or {})))

        doc = pq(r.content)('#filter-categories')
        a = pq(r.content)('#filter-categories').children('li').eq(0).find('a')
        # Note: PyQuery's `hasClass` matches children's classes, so yeah.
        eq_(a.attr('class'), 'sel' if not cat_selected else None,
            "'Any Category' should be selected")
        eq_(a.length, 1)
        eq_(a.text(), 'Any Category')

        a = doc('li:last').find('a')
        eq_(a.text(), unicode(self.cat.name))
        eq_(a.attr('class'), 'sel' if cat_selected else None,
            '%r should be selected' % unicode(self.cat.name))
        params.update(cat=self.cat.id)
        eq_(a.attr('href'), urlparams(self.url, **params))

    def test_no_cat(self):
        self.check_cat_filter({})

    def test_known_cat(self):
        self.check_cat_filter({'cat': self.cat.id})

    @amo.tests.mock_es
    def test_unknown_cat(self):
        # `cat=999` should get removed from the querystring.
        r = self.client.get(self.url, {'price': 'free', 'cat': '999'})
        self.assertRedirects(r, urlparams(self.url, price='free'))
        r = self.client.get(self.url, {'cat': '999'})
        self.assertRedirects(r, self.url)

    def test_cat_from_unreviewed_app(self):
        # Create an unreviewed app and assign to a category.
        cat = Category.objects.create(name='Bad Cats', type=amo.ADDON_WEBAPP)
        app = amo.tests.app_factory()
        AddonCategory.objects.create(addon=app, category=cat)
        app.update(status=amo.STATUS_PENDING)
        self.refresh()
        # Make sure category isn't listed in the results.
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'Bad Cats' not in res.content, (
            'Category of unreviewed apps should not show up in facets.')

    def check_price_filter(self, price, selected, type_=None):
        self.setup_paid(type_=type_)
        self.refresh()

        r = self.client.get(self.url, {'price': price})
        eq_(r.status_code, 200)
        links = pq(r.content)('#filter-prices a')
        expected = [
            ('Any Price', self.url),
            ('Free Only', urlparams(self.url, price='free')),
            ('Premium Only', urlparams(self.url, price='paid')),
        ]
        amo.tests.check_links(expected, links, selected)
        return list(r.context['pager'].object_list)

    def test_free_and_premium(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        eq_(self.check_price_filter('', 'Any Price'), self.both)

    def test_free_and_premium_inapp(self):
        raise SkipTest
        eq_(self.check_price_filter('', 'Any Price', amo.ADDON_PREMIUM_INAPP),
            self.both)

    def test_free_and_inapp_only(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        eq_(self.check_price_filter('free', 'Free Only',
                                    amo.ADDON_FREE_INAPP), self.free)

    def test_premium_only(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        eq_(self.check_price_filter('paid', 'Premium Only'), self.paid)

    def test_premium_inapp_only(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        eq_(self.check_price_filter('paid', 'Premium Only',
                                    amo.ADDON_PREMIUM_INAPP), self.paid)

    def test_free_other(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        eq_(self.check_price_filter('free', 'Free Only',
                                    amo.ADDON_OTHER_INAPP), self.free)

    def setup_devices(self):
        self._generate(3)
        for name, idx in DEVICE_CHOICES_IDS.iteritems():
            AddonDeviceType.objects.create(addon=self.apps[idx],
                device_type=idx)

        # Make an app have compatibility for every device.
        for x in xrange(1, 4):
            AddonDeviceType.objects.create(addon=self.apps[0],
                                           device_type=x)

    def check_device_filter(self, device, selected):
        raise SkipTest('See bug 785898')
        self.setup_devices()
        self.reindex(Webapp)

        r = self.client.get(self.url, {'device': device})
        eq_(r.status_code, 200)
        links = pq(r.content)('#device-facets a')
        expected = [
            ('Any Device', self.url),
            ('Desktop', urlparams(self.url, device='desktop')),
            ('Mobile', urlparams(self.url, device='mobile')),
            ('Tablet', urlparams(self.url, device='tablet')),
        ]
        amo.tests.check_links(expected, links, selected)
        return sorted(a.id for a in r.context['pager'].object_list)

    def test_device_all(self):
        eq_(self.check_device_filter('', 'Any Device'),
            sorted(a.id for a in self.apps))

    def test_device_desktop(self):
        eq_(self.check_device_filter('desktop', 'Desktop'),
            sorted([self.apps[0].id, self.apps[1].id]))

    def test_device_mobile(self):
        eq_(self.check_device_filter('mobile', 'Mobile'),
            sorted([self.apps[0].id, self.apps[2].id]))

    def test_device_tablet(self):
        eq_(self.check_device_filter('tablet', 'Tablet'),
            sorted([self.apps[0].id, self.apps[3].id]))

    def test_results_sort_default(self):
        raise SkipTest('until popularity sort is fixed, bug 785976')
        self._generate(3)
        self.check_sort_links(None, 'Relevance', 'popularity')

    def test_results_sort_unknown(self):
        self._generate(3)
        self.check_sort_links('xxx', 'Relevance')

    def test_results_sort_downloads(self):
        self._generate(3)
        self.check_sort_links('downloads', 'Weekly Downloads',
                              'weekly_downloads')

    def test_results_sort_rating(self):
        self._generate(3)
        self.check_sort_links('rating', 'Top Rated', 'bayesian_rating')

    def test_results_sort_newest(self):
        self._generate(3)
        self.check_sort_links('created', 'Newest', 'created')

    def test_price_sort_visible_for_paid_search(self):
        # 'Sort by Price' option should be preserved if filtering by paid apps.
        r = self.client.get(self.url, {'price': 'paid'})
        eq_(r.status_code, 200)
        assert 'price' in dict(r.context['sort_opts']), 'Missing price sort'

    def test_price_sort_visible_for_paid_browse(self):
        # 'Sort by Price' option should be removed if filtering by free apps.
        r = self.client.get(reverse('browse.apps'),
                            {'price': 'free', 'sort': 'popularity'})
        eq_(r.status_code, 200)
        assert 'price' not in dict(r.context['sort_opts']), (
            'Unexpected price sort')

    def test_price_sort_visible_for_free(self):
        # 'Sort by Price' option should be removed if filtering by free apps.
        r = self.client.get(self.url, {'price': 'free'})
        eq_(r.status_code, 200)
        assert 'price' not in dict(r.context['sort_opts']), (
            'Unexpected price filter')

    def test_paid_price_sort(self):
        for url in [self.url, reverse('browse.apps')]:
            r = self.client.get(url, {'price': 'paid', 'sort': 'price'})
            eq_(r.status_code, 200)

    def test_redirect_free_price_sort(self):
        for url in [self.url, reverse('browse.apps')]:
            # `sort=price` should be changed to `sort=downloads` if
            # `price=free` is in querystring.
            r = self.client.get(url, {'price': 'free', 'sort': 'price'})
            self.assert3xx(r, urlparams(url, price='free', sort='popularity'),
                           302)

    def test_region_exclusions(self):
        self.skip_if_disabled(settings.REGION_STORES)

        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)
        for region in mkt.regions.REGIONS_DICT:
            self.check_results({'q': 'Steam', 'region': region},
                               [] if region == 'br' else [self.webapp.id])

    @mock.patch.object(mkt.regions.BR, 'adolescent', True)
    def test_adolescent_popularity(self):
        self.skip_if_disabled(settings.REGION_STORES)

        # Adolescent regions use global popularity.

        # Webapp:   Global: 0, Regional: 0
        # Unknown1: Global: 1, Regional: 1 + 10 * 1 = 11
        # Unknown2: Global: 2, Regional: 0

        user = UserProfile.objects.all()[0]
        cd = ClientData.objects.create(region=mkt.regions.BR.id)

        unknown1 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown1, user=user, client_data=cd)

        unknown2 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown2, user=user)
        Installed.objects.create(addon=unknown2, user=user)

        self.reindex(Webapp)

        r = self.check_results({'sort': 'popularity',
                                'region': mkt.regions.BR.slug},
                               [unknown2.id, unknown1.id, self.webapp.id])

        # Check the actual popularity scores.
        by_popularity = list(r.context['pager'].object_list
                              .values_dict('popularity'))
        eq_(by_popularity,
            [{'id': unknown2.id, 'popularity': 2},
             {'id': unknown1.id, 'popularity': 1},
             {'id': self.webapp.id, 'popularity': 0}])


class TestSuggestions(TestAjaxSearch):

    def setUp(self):
        super(TestSuggestions, self).setUp()
        self.url = reverse('search.apps_ajax')

        self.c1 = Category.objects.create(name='groovy',
            type=amo.ADDON_WEBAPP)
        self.c2 = Category.objects.create(name='awesome',
            type=amo.ADDON_WEBAPP)

        self.w1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
            name='groovy app 1')
        self.w2 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
            name='awesome app 2')

        AddonCategory.objects.create(category=self.c1, addon=self.w1)
        AddonCategory.objects.create(category=self.c2, addon=self.w2)

        self.reindex(Webapp)

    def check_suggestions(self, url, params, addons=()):
        r = self.client.get(url + '?' + params)
        eq_(r.status_code, 200)

        data = json.loads(r.content)
        eq_(len(data), len(addons))

        data = sorted(data, key=lambda x: int(x['id']))
        addons = sorted(addons, key=lambda x: x.id)

        for got, expected in zip(data, addons):
            eq_(int(got['id']), expected.id)
            eq_(got['name'], unicode(expected.name))

    def test_webapp_search(self):
        self.check_suggestions(self.url,
            'q=app&category=', addons=[self.w1, self.w2])
        self.check_suggestions(self.url,
            'q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(self.url,
            'q=app&category=%d' % self.c2.id, addons=[self.w2])

    def test_region_exclusions(self):
        self.skip_if_disabled(settings.REGION_STORES)

        AER.objects.create(addon=self.w2, region=mkt.regions.BR.id)

        self.check_suggestions(self.url,
            'region=br&q=app&category=', addons=[self.w1])
        self.check_suggestions(self.url,
            'region=br&q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(self.url,
            'region=br&q=app&category=%d' % self.c2.id, addons=[])

        self.check_suggestions(self.url,
            'region=ca&q=app&category=', addons=[self.w1, self.w2])
        self.check_suggestions(self.url,
            'region=ca&q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(self.url,
            'region=ca&q=app&category=%d' % self.c2.id, addons=[self.w2])


class TestFilterMobileCompat(amo.tests.ESTestCase):
    """
    Test that apps that are incompatible with mobile are hidden from any
    listings.
    """

    def setUp(self):
        self.app_name = 'Basta Pasta'
        self.webapp = Webapp.objects.create(name=self.app_name,
                                            type=amo.ADDON_WEBAPP,
                                            status=amo.STATUS_PUBLIC)
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=amo.DEVICE_DESKTOP.id)
        self.reindex(Webapp)

        self.mcompat = None
        self.client.login(username='admin@mozilla.com', password='password')

    @nottest
    def test_url(self, url, app_is_mobile=True, browser_is_mobile=False):
        """
        Test a view to make sure that it excludes mobile-incompatible apps
        from its listings.
        """
        url = urlparams(url, mobile='true' if browser_is_mobile else 'false')

        if app_is_mobile:
            # If the app is supposed to be mobile and we haven't created the
            # AddonDeviceType object yet, create it.
            self.mcompat = AddonDeviceType.objects.create(
                addon=self.webapp, device_type=amo.DEVICE_MOBILE.id)
            self.mcompat.save()
            self.reindex(Webapp)

        self.refresh()
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)

        # If the browser is mobile and the app is not mobile compatible, assert
        # that the app doesn't show up in the listing.
        if browser_is_mobile and not app_is_mobile:
            assert self.app_name not in r.content, (
                'Found non-mobile app for %s' % url)
        else:
            # Otherwise assert that it does.
            assert self.app_name in r.content, (
                "Couldn't find mobile app for %s" % url)

        # Cleanup
        if app_is_mobile:
            # If the app is not mobile and we haven't destroyed the
            # AddonDeviceType from a previous test, destroy it now.
            self.mcompat.delete()
            self.reindex(Webapp)
            self.mcompat = None

    def _generate(self):
        views = [reverse('browse.apps'),
                 reverse('search.search') + '?q=',
                 reverse('search.search') + '?q=Basta',
                 reverse('search.suggestions') + '?q=Basta&cat=apps']

        for view in views:
            for app_is_mobile in (True, False):
                for browser_is_mobile in (False, True):
                    yield self.test_url, view, app_is_mobile, browser_is_mobile

    def test_generator(self):
        # This is necessary until we can get test generator methods worked out
        # to run properly.
        for test_params in self._generate():
            func, params = test_params[0], test_params[1:]
            func(*params)

    def test_mobile_applied_filters(self):
        # These tests are currently invalid so skip:
        raise SkipTest

        # Test that we don't show the controls to search by device type in the
        # search results.
        url = urlparams(reverse('search.search'), q='Basta')

        resp_desktop = self.client.get(url, {'mobile': 'false'})
        resp_mobile = self.client.get(url, {'mobile': 'true'})

        eq_(resp_desktop.status_code, 200)
        eq_(resp_mobile.status_code, 200)

        p_desktop = pq(resp_desktop.content)
        p_mobile = pq(resp_mobile.content)

        assert p_desktop('#device-facets')
        assert not p_mobile('#device-facets')

        assert not p_desktop('.applied-filters')
        assert not p_mobile('.applied-filters')

    @amo.tests.mobile_test
    def test_mobile_no_flash(self):
        a = amo.tests.app_factory()
        a.name = 'Basta Addendum'
        AddonDeviceType.objects.create(
            addon=self.webapp,
            device_type=amo.DEVICE_MOBILE.id)
        AddonDeviceType.objects.create(
            addon=a,
            device_type=amo.DEVICE_MOBILE.id)
        a.save()
        af = a.get_latest_file()
        af.uses_flash = True
        af.save()
        a.save()
        self.reindex(Webapp)
        r = self.client.get(urlparams(reverse('search.search'), q='Basta'))
        eq_(r.status_code, 200)
        eq_(list(r.context['pager'].object_list), [self.webapp])
