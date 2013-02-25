import json

import mock
from nose import SkipTest
from nose.tools import eq_, nottest
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo
import amo.tests
from addons.models import AddonDeviceType, Category
from addons.tasks import index_addon_held
from amo.urlresolvers import reverse
from amo.utils import urlparams
from search.tests.test_views import TestAjaxSearch
from stats.models import ClientData
from users.models import UserProfile

import mkt
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.search.views import _app_search
from mkt.webapps.tests.test_views import PaidAppMixin
from mkt.webapps.models import AddonExcludedRegion as AER, Installed, Webapp


class FakeES(object):
    """Maybe we'll use this in the future to test what gets sent to ES."""

    def __init__(self, **kw):
        self.expected = kw.pop('expected', None)
        return super(FakeES, self).__init__(**kw)

    def search(self, query, indexes=None, doc_types=None, **query_params):
        eq_(self.expected, query)
        return {'hits': {'hits': [], 'total': 0}, 'took': 0}


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
        self.webapp.addoncategory_set.create(category=self.cat)
        # Emit post-save signal so the app gets reindexed.
        self.webapp.save()
        self.refresh()

    def _generate(self, num=3):
        for x in xrange(num):
            app = amo.tests.app_factory()
            app.addoncategory_set.create(category=self.cat)
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
        # Testing the correct download source like a bawse!
        eq_(a.attr('href'),
            urlparams(self.webapp.get_url_path(), src='mkt-search'))

    def check_cat_filter(self, params):
        raise SkipTest('until category filtering comes back')
        cat_selected = params.get('cat') == self.cat.id
        r = self.client.get(self.url)
        pager = r.context['pager']

        r = self.client.get(urlparams(self.url, **params))
        eq_(list(r.context['pager'].object_list), list(pager.object_list),
            '%s != %s' % (self.url, urlparams(self.url, **params or {})))

        doc = pq(r.content)('#filter-categories')
        a = pq(r.content)('#filter-categories').children('li').eq(0).find('a')

        # :last will no longer work
        a = doc('li').eq(1).find('a')
        eq_(a.text(), unicode(self.cat.name))
        if cat_selected:
            eq_(a.filter('.sel').length, 1,
                '%r should be selected' % unicode(self.cat.name))
        else:
            eq_(a.filter('.button').length, 1,
                '%r should be selected' % unicode(self.cat.name))

        params.update(cat=self.cat.id)
        eq_(a.attr('href'), urlparams(self.url, **params))

        sorts = pq(r.content)('#filter-sort')
        href = sorts('li:first-child a').attr('href')

        if cat_selected:
            self.assertNotEqual(href.find('sort=popularity'), -1,
                'Category found - first sort option should be Popularity')
        else:
            eq_(href, '/search/?sort=None',
                'Category found - first sort option should be Relevancy')

    def test_no_cat(self):
        self.check_cat_filter({})

    def test_known_cat(self):
        self.check_cat_filter({'cat': self.cat.id})

    def test_cat_from_unreviewed_app(self):
        # Create an unreviewed app and assign to a category.
        cat = Category.objects.create(name='Bad Cats', type=amo.ADDON_WEBAPP)
        app = amo.tests.app_factory()
        app.addoncategory_set.create(category=cat)
        app.update(status=amo.STATUS_PENDING)
        self.refresh()
        # Make sure category isn't listed in the results.
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'Bad Cats' not in res.content, (
            'Category of unreviewed apps should not show up in facets.')

    def test_hide_paid_apps_on_android(self):
        self.setup_paid()
        self.refresh()
        res = self.client.get(self.url, {'mobile': 'true'})
        self.assertSetEqual(res.context['pager'].object_list, self.free)

    def check_price_filter(self, price, selected, type_=None):
        self.setup_paid(type_=type_)
        self.refresh()

        r = self.client.get(self.url, {'price': price})
        eq_(r.status_code, 200)
        doc = pq(r.content)
        links = doc('#filter-prices a')
        expected = [
            ('Any Price', self.url),
            ('Free Only', urlparams(self.url, price='free')),
            ('Premium Only', urlparams(self.url, price='paid')),
        ]
        amo.tests.check_links(expected, links, selected)

        eq_(doc('#filters-body input[name=price]').attr('value'), price)

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
        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)
        for region in mkt.regions.REGIONS_DICT:
            self.check_results({'q': 'Steam', 'region': region},
                               [] if region == 'br' else [self.webapp.id])

    @mock.patch.object(mkt.regions.BR, 'adolescent', True)
    def test_adolescent_popularity(self):
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

        self.w1.addoncategory_set.create(category=self.c1)
        self.w2.addoncategory_set.create(category=self.c2)

        index_addon_held([self.w1.id, self.w2.id])
        self.refresh()

    def check_suggestions(self, url, params, addons=()):
        r = self.client.get(url + '?' + params)
        eq_(r.status_code, 200)

        data = json.loads(r.content)
        eq_(len(data), len(addons))

        data = sorted(data, key=lambda x: x['name'])
        addons = sorted(addons, key=lambda x: x.name)
        eq_(len(data), len(addons))

        for got, expected in zip(data, addons):
            eq_(got['name'], unicode(expected.name))
            eq_(int(got['id']), expected.id)

    def test_webapp_search(self):
        self.check_suggestions(self.url, 'q=app&category=',
            addons=[self.w1, self.w2])
        self.check_suggestions(
            self.url, 'q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(
            self.url, 'q=app&category=%d' % self.c2.id, addons=[self.w2])

    def test_region_exclusions(self):
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
    def test_url(self, url, app_is_mobile=True, browser_is_mobile=False,
                 user_agent=None):
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
        headers = dict()
        if user_agent:
            headers['HTTP_USER_AGENT'] = user_agent
        r = self.client.get(url, follow=True, **headers)
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

        gaia_ua = 'Mozilla/5.0 (Mobile; rv:18.0) Gecko/18.0 Firefox/18.0'
        for view in views:
            # A desktop-only app should should not appear on mobile.
            yield self.test_url, view, False, True, gaia_ua

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


class TestFilterGaiaCompat(amo.tests.ESTestCase):
    """
    Test that premium apps outside of B2G(gaia) are hidden from any listings.
    """

    def setUp(self):
        self.app_name = 'Basta Pasta'
        self.webapp = Webapp.objects.create(name=self.app_name,
                                            type=amo.ADDON_WEBAPP,
                                            status=amo.STATUS_PUBLIC)
        self.make_premium(self.webapp)
        self.reindex(Webapp)

    @mock.patch('mkt.search.views._filter_search')
    def test_packaged_visible_on_gaia(self, _filter_search_mock):
        self.webapp.update(is_packaged=True)
        self.refresh()
        request = RequestFactory().get(reverse('search.search'))
        request.GAIA = True
        request.MOBILE = True
        request.TABLET = False

        _app_search(request)
        req, qs, query = _filter_search_mock.call_args[0]
        eq_(list(qs), [self.webapp])
        eq_(query['device'], 'gaia')

    @mock.patch('mkt.search.views._filter_search')
    def test_packaged_visible_on_desktop(self, _filter_search_mock):
        self.webapp.update(is_packaged=True)
        self.refresh()
        request = RequestFactory().get(reverse('search.search'))
        request.GAIA = False
        request.MOBILE = False
        request.TABLET = False

        _app_search(request)
        req, qs, query = _filter_search_mock.call_args[0]
        eq_(list(qs), [])
        eq_(query['device'], None)

    @mock.patch('mkt.search.views._filter_search')
    def test_packaged_hidden_on_android(self, _filter_search_mock):
        self.webapp.update(is_packaged=True)
        self.refresh()
        request = RequestFactory().get(reverse('search.search'))
        request.GAIA = False
        request.MOBILE = True
        request.TABLET = False

        _app_search(request)
        req, qs, query = _filter_search_mock.call_args[0]
        eq_(list(qs), [])
        eq_(query['device'], 'mobile')

    @nottest
    def test_url(self, url, data, show_paid=False):
        """
        Test a view to make sure that it excludes premium apps from non gaia
        devices.
        """
        self.refresh()
        r = self.client.get(url, data, follow=True)
        eq_(r.status_code, 200)

        if show_paid:
            assert self.app_name not in r.content, (
                'Found premium app for %s' % url)
        else:
            assert self.app_name in r.content, (
                "Couldn't find premium app for %s" % url)

    def _generate(self):
        views = [reverse('browse.apps'),
                 reverse('search.search') + '?q=',
                 reverse('search.search') + '?q=Basta',
                 reverse('search.suggestions') + '?q=Basta&cat=apps']

        for url in views:
            yield self.test_url, url, {'mobile': 'true', 'tablet': 'true'}, False
            yield self.test_url, url, {'mobile': 'true', 'gaia': 'false'}, False
            yield self.test_url, url, {'mobile': 'true', 'gaia': 'true'}, True
            yield self.test_url, url, {}, True

    def test_generator(self):
        # This is necessary until we can get test generator methods worked out
        # to run properly.
        for test_params in self._generate():
            func, params = test_params[0], test_params[1:]
            func(*params)
