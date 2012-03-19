import json

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from amo.helpers import numberfmt
import amo.tests
from amo.utils import urlparams
from amo.urlresolvers import reverse
from addons.models import AddonCategory, AddonDeviceType, Category, DeviceType
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.webapps.models import Webapp
from mkt.webapps.tests.test_views import PaidAppMixin


class SearchBase(amo.tests.ESTestCase):

    def get_results(self, r, sort=False):
        """Return pks of add-ons shown on search results page."""
        results = [a.id for a in r.context['pager'].object_list]
        if sort:
            results = sorted(results)
        return results

    def check_sort_links(self, key, title=None, sort_by=None, reverse=True,
                         params={}):
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
        assert 'X-Requested-With' in r['vary'].split(','), (
            'Expected "Vary: X-Requested-With" header')
        self.assertTemplateUsed(r, 'search/results.html')

    def test_results_item(self):
        r = self.client.get(self.url)
        item = pq(r.content)('.items .item')
        eq_(item.length, 1)
        a = item.find('h3 a')
        eq_(a.text(), unicode(self.webapp.name))
        eq_(a.attr('href'),
            urlparams(self.webapp.get_url_path(), src='search'))

    def test_results_downloads(self):
        for sort in ('', 'downloads', 'created'):
            r = self.client.get(urlparams(self.url, sort=sort))
            dls = pq(r.content)('.item .downloads')
            eq_(dls.text().split()[0],
                numberfmt(self.webapp.weekly_downloads),
                'Missing downloads for %s' % sort)

    def check_cat_filter(self, params, valid):
        cat_selected = params.get('cat') == self.cat.id
        r = self.client.get(self.url)
        pager = r.context['pager']

        r = self.client.get(urlparams(self.url, **params))
        if valid:
            eq_(list(r.context['pager'].object_list), list(pager.object_list),
                '%s != %s' % (self.url, urlparams(self.url, **params or {})))

        doc = pq(r.content)('#category-facets')
        li = doc.children('li:first-child')
        # Note: PyQuery's `hasClass` matches children's classes, so yeah.
        eq_(li.attr('class'), 'selected' if not cat_selected else None,
            "'All Apps' should be selected")
        a = li.children('a')
        eq_(a.length, 1)
        eq_(a.text(), 'All Apps')

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
        self.check_cat_filter({}, valid=True)

    def test_known_cat(self):
        self.check_cat_filter({'cat': self.cat.id}, valid=True)

    def test_unknown_cat(self):
        self.check_cat_filter({'cat': 999}, valid=False)

    def check_price_filter(self, price, selected, type_=None):
        self.setup_paid(type_=type_)
        self.refresh()

        r = self.client.get(self.url, {'price': price})
        eq_(r.status_code, 200)
        links = pq(r.content)('#price-facets a')
        expected = [
            ('Free & Premium', self.url),
            ('Free Only', urlparams(self.url, price='free')),
            ('Premium Only', urlparams(self.url, price='paid')),
        ]
        amo.tests.check_links(expected, links, selected)
        return list(r.context['pager'].object_list)

    def test_free_and_premium(self):
        eq_(self.check_price_filter('', 'Free & Premium'), self.both)

    def test_free_and_premium_inapp(self):
        eq_(self.check_price_filter('', 'Free & Premium',
                                     amo.ADDON_PREMIUM_INAPP),
            self.both)

    def test_free_and_inapp_only(self):
        eq_(self.check_price_filter('free', 'Free Only',
                                     amo.ADDON_FREE_INAPP), self.free)

    def test_premium_only(self):
        eq_(self.check_price_filter('paid', 'Premium Only'), self.paid)

    def test_premium_inapp_only(self):
        eq_(self.check_price_filter('paid', 'Premium Only',
                                     amo.ADDON_PREMIUM_INAPP), self.paid)

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
