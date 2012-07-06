import json

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import AddonCategory, AddonDeviceType, Category, DeviceType
from amo.helpers import numberfmt
from amo.urlresolvers import reverse
from amo.utils import urlparams
from market.models import AddonPremium, Price
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.webapps.models import Webapp
from mkt.webapps.tests.test_views import PaidAppMixin

from search.tests.test_views import TestAjaxSearch


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
        doc = pq(r.content)
        if title:
            eq_(doc('#sorter .selected').text(), title)
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

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')

    def test_results_item(self):
        r = self.client.get(self.url)
        item = pq(r.content)('.items .item')
        eq_(item.length, 1)
        a = item.find('h3 a')
        eq_(a.text(), unicode(self.webapp.name))
        eq_(a.attr('href'),
            urlparams(self.webapp.get_url_path(), src='mkt-search'))

    def test_results_downloads(self):
        for sort in ('', 'downloads', 'created'):
            r = self.client.get(urlparams(self.url, sort=sort))
            dls = pq(r.content)('.item .downloads')
            eq_(dls.text().split()[0],
                numberfmt(self.webapp.weekly_downloads),
                'Missing downloads for %s' % sort)

    def check_cat_filter(self, params):
        cat_selected = params.get('cat') == self.cat.id
        r = self.client.get(self.url)
        pager = r.context['pager']

        r = self.client.get(urlparams(self.url, **params))
        eq_(list(r.context['pager'].object_list), list(pager.object_list),
            '%s != %s' % (self.url, urlparams(self.url, **params or {})))

        doc = pq(r.content)('#category-facets')
        li = doc.children('li:first-child')
        # Note: PyQuery's `hasClass` matches children's classes, so yeah.
        eq_(li.attr('class'), 'selected' if not cat_selected else None,
            "'Any Category' should be selected")
        a = li.children('a')
        eq_(a.length, 1)
        eq_(a.text(), 'Any Category')

        li = doc('li:last')
        eq_(li.attr('class'), 'selected' if cat_selected else None,
            '%r should be selected' % unicode(self.cat.name))
        a = li.children('a')
        eq_(a.text(), unicode(self.cat.name))
        params.update(cat=self.cat.id)
        eq_(a.attr('href'), urlparams(self.url, **params))
        eq_(json.loads(a.attr('data-params')),
            {'cat': self.cat.id, 'page': None})

    def test_no_cat(self):
        self.check_cat_filter({})

    def test_known_cat(self):
        self.check_cat_filter({'cat': self.cat.id})

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
        links = pq(r.content)('#price-facets a')
        expected = [
            ('Any Price', self.url),
            ('Free Only', urlparams(self.url, price='free')),
            ('Premium Only', urlparams(self.url, price='paid')),
        ]
        amo.tests.check_links(expected, links, selected)
        return list(r.context['pager'].object_list)

    def test_free_and_premium(self):
        eq_(self.check_price_filter('', 'Any Price'), self.both)

    def test_free_and_premium_inapp(self):
        eq_(self.check_price_filter('', 'Any Price', amo.ADDON_PREMIUM_INAPP),
            self.both)

    def test_free_and_inapp_only(self):
        eq_(self.check_price_filter('free', 'Free Only',
                                    amo.ADDON_FREE_INAPP), self.free)

    def test_free_and_premium_other(self):
        eq_(self.check_price_filter('', 'Any Price', amo.ADDON_PREMIUM_OTHER),
            self.both)

    def test_premium_only(self):
        eq_(self.check_price_filter('paid', 'Premium Only'), self.paid)

    def test_premium_inapp_only(self):
        eq_(self.check_price_filter('paid', 'Premium Only',
                                    amo.ADDON_PREMIUM_INAPP), self.paid)

    def test_premium_other(self):
        eq_(self.check_price_filter('paid', 'Premium Only',
                                    amo.ADDON_PREMIUM_OTHER), self.paid)

    def test_premium_other_zero(self):
        price = Price.objects.create(price=0)
        app = amo.tests.app_factory(weekly_downloads=1)
        AddonPremium.objects.create(price=price, addon=app)
        app.update(premium_type=amo.ADDON_PREMIUM_OTHER)
        eq_(self.check_price_filter('paid', 'Premium Only',
                                    amo.ADDON_PREMIUM_OTHER),
            self.paid + [app])

    def setup_devices(self):
        self._generate(3)
        for name, idx in DEVICE_CHOICES_IDS.iteritems():
            AddonDeviceType.objects.create(addon=self.apps[idx],
                device_type=DeviceType.objects.create(name=name, id=idx))

        # Make an app have compatibility for every device.
        for x in xrange(1, 4):
            AddonDeviceType.objects.create(addon=self.apps[0],
                                           device_type_id=x)

    def check_device_filter(self, device, selected):
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
        self._generate(3)
        self.check_sort_links(None, 'Relevance', 'weekly_downloads')

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
                            {'price': 'free', 'sort': 'downloads'})
        eq_(r.status_code, 200)
        assert 'price' not in dict(r.context['sort_opts']), (
            'Unexpected price sort')

    def test_price_sort_visible_for_free(self):
        # 'Sort by Price' option should be removed if filtering by free apps.
        r = self.client.get(self.url, {'price': 'free'})
        eq_(r.status_code, 200)
        assert 'price' not in dict(r.context['sort_opts']), (
            'Unexpected price sort')

    def test_paid_price_sort(self):
        for url in [self.url, reverse('browse.apps')]:
            r = self.client.get(url, {'price': 'paid', 'sort': 'price'})
            eq_(r.status_code, 200)

    def test_redirect_free_price_sort(self):
        for url in [self.url, reverse('browse.apps')]:
            # `sort=price` should be removed if `price=free` is in querystring.
            r = self.client.get(url, {'price': 'free', 'sort': 'price'})
            self.assertRedirects(r, urlparams(url, price='free'))


class SuggestionsTests(TestAjaxSearch):

    def check_suggestions(self, url, params, addons=()):
        r = self.client.get(url + '?' + params)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        data.sort(key=lambda x: x['id'])
        addons.sort(key=lambda x: x.id)
        eq_(len(data), len(addons))
        for got, expected in zip(data, addons):
            eq_(int(got['id']), expected.id)
            eq_(got['name'], unicode(expected.name))

    def test_webapp_search(self):
        url = reverse('search.apps_ajax')
        c1 = Category.objects.create(name='groovy',
                                     type=amo.ADDON_WEBAPP)
        c2 = Category.objects.create(name='awesome',
                                     type=amo.ADDON_WEBAPP)
        g1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                   name='groovy app 1',
                                   type=amo.ADDON_WEBAPP)
        a2 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                   name='awesome app 2',
                                   type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(category=c1, addon=g1)
        AddonCategory.objects.create(category=c2, addon=a2)
        self.client.login(username='admin@mozilla.com', password='password')
        for a in Webapp.objects.all():
            a.save()
        self.refresh()
        self.check_suggestions(url, "q=app&category=", addons=[g1, a2])
        self.check_suggestions(url, "q=app&category=%d" % c1.id, addons=[g1])
        self.check_suggestions(url, "q=app&category=%d" % c2.id, addons=[a2])
