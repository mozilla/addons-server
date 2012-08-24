import datetime
from django.conf import settings

from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.tests import mock_es
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import AddonCategory, Category, AddonDeviceType

import mkt
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


class BrowseBase(amo.tests.ESTestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                           type=amo.ADDON_WEBAPP)
        self.url = reverse('browse.apps', args=[self.cat.slug])
        self.webapp = Webapp.objects.get(id=337141)
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        self.webapp.save()
        self.refresh()

    def get_pks(self, key, url, data=None):
        r = self.client.get(url, data or {})
        eq_(r.status_code, 200)
        return sorted(x.id for x in r.context[key])

    def make_featured(self, app, category=None):
        f = FeaturedApp.objects.create(app=app, category=category)
        # Feature in the US region.
        FeaturedAppRegion.objects.create(featured_app=f,
                                         region=mkt.regions.US.id)
        return f

    def setup_featured(self):
        self.skip_if_disabled(settings.REGION_STORES)

        # Category featured.
        a = amo.tests.app_factory()
        self.make_featured(app=a, category=self.cat)

        b = amo.tests.app_factory()
        self.make_featured(app=b, category=self.cat)

        # Home featured.
        c = amo.tests.app_factory()
        self.make_featured(app=c, category=None)

        return a, b, c

    def setup_popular(self):
        # When run individually these tests always pass fine.
        # But when run alongside all the other tests, they sometimes fail.
        # WTMF.
        # TODO: Figure out why ES flakes out on every other test run!
        # (I'm starting to think the "elastic" in elasticsearch is symbolic
        # of how our problems keep bouncing back. I thought elastic had more
        # potential. Maybe it's too young? I play with an elastic instrument;
        # would you like to join my rubber band? Our sounds will resin-ate
        # across this vulcan land. [P.S. If you can help in any
        # way, pun-wise or code-wise, please don't hesitate to do so.] In the
        # meantime, SkipTest is the rubber band to our elastic problems.)
        raise SkipTest
        self.skip_if_disabled(settings.REGION_STORES)

        # Popular for this category.
        a = amo.tests.app_factory()
        AddonCategory.objects.create(addon=a, category=self.cat)
        a.save()

        # Popular and category featured and home featured.
        self.make_featured(app=self.webapp, category=self.cat)
        self.make_featured(app=self.webapp, category=None)

        self.refresh()

        return a

    def _test_featured(self):
        """This is common to / and /apps/, so let's be DRY."""
        a, b, c = self.setup_featured()
        # Check that the Home featured app is shown only in US region.
        for region in mkt.regions.REGIONS_DICT:
            eq_(self.get_pks('featured', self.url, {'region': region}),
                [c.id] if region == 'us' else [])

    def _test_featured_region_exclusions(self):
        a, b, c = self.setup_featured()
        AER.objects.create(addon=c, region=mkt.regions.BR.id)

        # Feature this app in all regions.
        f = c.featuredapp_set.all()[0]

        for region_id in mkt.regions.REGIONS_CHOICES_ID_DICT:
            # `setup_featured` already added this to the US region.
            if region_id == mkt.regions.US.id:
                continue
            FeaturedAppRegion.objects.create(featured_app=f,
                                             region=region_id)

        for region in mkt.regions.REGIONS_DICT:
            eq_(self.get_pks('featured', self.url, {'region': region}),
                [] if region == 'br' else [c.id])

    def _test_popular_pks(self, url, pks):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        results = r.context['popular']

        # Test correct apps.
        eq_(sorted(r.id for r in results), sorted(pks))

        # Test sort order.
        expected = sorted(results, key=lambda x: x.weekly_downloads,
                          reverse=True)
        eq_(list(results), expected)

    def _test_popular(self):
        a = self.setup_popular()
        # Check that these apps are shown.
        self._test_popular_pks(self.url, [self.webapp.id, a.id])

    def _test_popular_region_exclusions(self):
        a = self.setup_popular()
        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)

        for region in mkt.regions.REGIONS_DICT:
            eq_(self.get_pks('popular', self.url, {'region': region}),
               [a.id] if region == 'br' else [self.webapp.id, a.id])


class TestIndexLanding(BrowseBase):

    def setUp(self):
        super(TestIndexLanding, self).setUp()
        self.url = reverse('browse.apps')

    @mock_es
    def test_good_cat(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/landing.html')

    @mock_es
    def test_featured(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        self._test_featured()

    @mock_es
    def test_featured_region_exclusions(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        self._test_featured_region_exclusions()

    def test_popular(self):
        self._test_popular()

    def test_popular_region_exclusions(self):
        self._test_popular_region_exclusions()

    def test_popular_flash(self):
        a = self.setup_popular()
        a.get_latest_file().update(uses_flash=True)
        self.refresh()
        # Check that these apps are shown on the category landing page.
        self._test_popular_pks(self.url, [self.webapp.id, a.id])

    @amo.tests.mobile_test
    def test_no_flash_on_mobile(self):
        a = self.setup_popular()
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=amo.DEVICE_MOBILE.id)
        AddonDeviceType.objects.create(addon=a,
                                       device_type=amo.DEVICE_MOBILE.id)
        a.get_latest_file().update(uses_flash=True)
        a.save()
        self.webapp.save()
        self.refresh()
        self._test_popular_pks(self.url, [self.webapp.id])


class TestIndexSearch(BrowseBase):

    def setUp(self):
        super(TestIndexSearch, self).setUp()
        self.url = reverse('browse.apps') + '?sort=downloads'

    def test_page(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')
        eq_(pq(r.content)('#page h1').text(), 'By Popularity')

    def test_good_sort_option(self):
        for sort in ('downloads', 'rating', 'price', 'created'):
            r = self.client.get(self.url, {'sort': sort})
            eq_(r.status_code, 200)

    def test_bad_sort_option(self):
        r = self.client.get(self.url, {'sort': 'xxx'})
        eq_(r.status_code, 200)

    def test_sorter(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        li = pq(r.content)('#sorter li:eq(0)')
        eq_(li.filter('.selected').length, 1)
        eq_(li.find('a').attr('href'),
            urlparams(reverse('browse.apps'), sort='downloads'))


class TestCategoryLanding(BrowseBase):

    def setUp(self):
        super(TestCategoryLanding, self).setUp()
        self.url = reverse('browse.apps', args=[self.cat.slug])

    def get_new_cat(self):
        return Category.objects.create(name='Slap Tickling', slug='booping',
                                       type=amo.ADDON_WEBAPP)

    @mock_es
    def test_good_cat(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/landing.html')

    @mock_es
    def test_bad_cat(self):
        r = self.client.get(reverse('browse.apps', args=['xxx']))
        eq_(r.status_code, 404)

    def test_empty_cat(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        cat = Category.objects.create(name='Empty', slug='empty',
                                      type=amo.ADDON_WEBAPP)
        cat_url = reverse('browse.apps', args=[cat.slug])
        r = self.client.get(cat_url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_featured(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        a, b, c = self.setup_featured()

        # Check that these apps are featured for this category -
        # and only in US region.
        for region in mkt.regions.REGIONS_DICT:
            eq_(self.get_pks('featured', self.url, {'region': region}),
                [a.id, b.id] if region == 'us' else [])

        # Check that these apps are not featured for another category.
        new_cat_url = reverse('browse.apps', args=[self.get_new_cat().slug])
        eq_(self.get_pks('featured', new_cat_url), [])

    def test_popular(self):
        a = self.setup_popular()

        # Check that these apps are shown for this category.
        self._test_popular_pks(self.url, [self.webapp.id, a.id])

        # Check that these apps are not shown for another category.
        new_cat_url = reverse('browse.apps', args=[self.get_new_cat().slug])
        eq_(self.get_pks('popular', new_cat_url), [])

    def test_popular_region_exclusions(self):
        a = self.setup_popular()

        AER.objects.create(addon=self.webapp, region=mkt.regions.BR.id)

        for region in mkt.regions.REGIONS_DICT:
            print region, self.get_pks('popular', self.url, {'region': region})
            eq_(self.get_pks('popular', self.url, {'region': region}),
                [a.id] if region == 'br' else [self.webapp.id, a.id])

    @mock_es
    def test_search_category(self):
        # Ensure category got set in the search form.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#search input[name=cat]').val(), str(self.cat.id))


class TestCategorySearch(BrowseBase):

    def setUp(self):
        super(TestCategorySearch, self).setUp()
        self.url = reverse('browse.apps',
                           args=[self.cat.slug]) + '?sort=downloads'

    @mock_es
    def test_good_cat(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')

    @mock_es
    def test_bad_cat(self):
        r = self.client.get(reverse('browse.apps', args=['xxx']),
                            {'sort': 'downloads'})
        eq_(r.status_code, 404)

    def test_non_indexed_cat(self):
        new_cat = Category.objects.create(name='Slap Tickling', slug='booping',
                                          type=amo.ADDON_WEBAPP)
        r = self.client.get(reverse('browse.apps', args=[new_cat.slug]),
                            {'sort': 'downloads'})

        # If the category has no indexed apps, we redirect to main search page.
        self.assertRedirects(r, reverse('search.search'))

    def test_sidebar(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        a = pq(r.content)('#category-facets .selected a')
        eq_(a.attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id))
        eq_(a.text(), unicode(self.cat.name))

    def test_sorter(self):
        # TODO(dspasovski): Fix this.
        raise SkipTest
        r = self.client.get(self.url)
        li = pq(r.content)('#sorter li:eq(0)')
        eq_(li.filter('.selected').length, 1)
        eq_(li.find('a').attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id,
                      sort='downloads'))

    @mock_es
    def test_search_category(self):
        # Ensure category got preserved in search term.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#search input[name=cat]').val(), str(self.cat.id))
