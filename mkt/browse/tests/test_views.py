from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import AddonCategory, Category
from mkt.webapps.models import Webapp
from mkt.zadmin.models import FeaturedApp


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

    def setup_featured(self):
        amo.tests.addon_factory()

        # Category featured.
        a = amo.tests.app_factory()
        FeaturedApp.objects.create(app=a, category=self.cat)

        b = amo.tests.app_factory()
        FeaturedApp.objects.create(app=b, category=self.cat)

        # Home featured.
        c = amo.tests.app_factory()
        FeaturedApp.objects.create(app=c, category=None)

        return a, b, c

    def setup_popular(self):
        # TODO: Figure out why ES flakes out on every other test run!
        # (I'm starting to think the "elastic" in elasticsearch is symbolic
        # of how our problems keep bouncing back. I thought elastic had more
        # potential. Maybe it's too young? I play with an elastic instrument;
        # would you like to join my rubber band? [P.S. If you can help in any
        # way, pun-wise or code-wise, please don't hesitate to do so.] In the
        # meantime, SkipTest is the rubber band to our elastic problems.)
        raise SkipTest

        amo.tests.addon_factory()

        # Popular without a category.
        a = amo.tests.app_factory()
        self.refresh()

        # Popular for this category.
        b = amo.tests.app_factory()
        AddonCategory.objects.create(addon=b, category=self.cat)
        b.save()

        # Popular and category featured and home featured.
        self.make_featured(webapp=self.webapp, group='category')
        self.make_featured(webapp=self.webapp, group='home')
        self.webapp.save()

        # Something's really up.
        self.refresh()

        return a, b

    def _test_popular(self, url, pks):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        results = r.context['popular']

        # Test correct apps.
        eq_(sorted(r.id for r in results), sorted(pks))

        # Test sort order.
        expected = sorted(results, key=lambda x: x.weekly_downloads,
                          reverse=True)
        eq_(list(results), expected)


class TestIndexLanding(BrowseBase):

    def setUp(self):
        super(TestIndexLanding, self).setUp()
        self.url = reverse('browse.apps')

    def test_good_cat(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/landing.html')

    def test_featured(self):
        a, b, c = self.setup_featured()
        # Check that these apps are featured on the category landing page.
        eq_(self.get_pks('featured', self.url), sorted([c.id]))

    def test_popular(self):
        a, b = self.setup_popular()
        # Check that these apps are shown on the category landing page.
        self._test_popular(self.url, [self.webapp.id, a.id, b.id])


class TestIndexSearch(BrowseBase):

    def setUp(self):
        super(TestIndexSearch, self).setUp()
        self.url = reverse('browse.apps') + '?sort=downloads'

    def test_page(self):
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

    def test_good_cat(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'browse/landing.html')

    def test_bad_cat(self):
        r = self.client.get(reverse('browse.apps', args=['xxx']))
        eq_(r.status_code, 404)

    def test_empty_cat(self):
        cat = Category.objects.create(name='Empty', slug='empty',
                                      type=amo.ADDON_WEBAPP)
        cat_url = reverse('browse.apps', args=[cat.slug])
        r = self.client.get(cat_url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_featured(self):
        a, b, c = self.setup_featured()

        # Check that these apps are featured for this category.
        eq_(self.get_pks('featured', self.url), sorted([a.id, b.id]))

        # Check that these apps are not featured for another category.
        new_cat_url = reverse('browse.apps', args=[self.get_new_cat().slug])
        eq_(self.get_pks('featured', new_cat_url), [])

    def test_popular(self):
        a, b = self.setup_popular()

        # Check that these apps are shown for this category.
        self._test_popular(self.url, [self.webapp.id, b.id])

        # Check that these apps are not shown for another category.
        new_cat_url = reverse('browse.apps', args=[self.get_new_cat().slug])
        eq_(self.get_pks('popular', new_cat_url), [])

    def test_search_category(self):
        # Ensure category got set in the search form.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#search input[name=cat]').val(), str(self.cat.id))


class TestCategorySearch(BrowseBase):

    def setUp(self):
        super(TestCategorySearch, self).setUp()
        self.url = reverse('browse.apps',
                           args=[self.cat.slug]) + '?sort=downloads'

    def test_good_cat(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')

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
        r = self.client.get(self.url)
        a = pq(r.content)('#category-facets .selected a')
        eq_(a.attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id))
        eq_(a.text(), unicode(self.cat.name))

    def test_sorter(self):
        r = self.client.get(self.url)
        li = pq(r.content)('#sorter li:eq(0)')
        eq_(li.filter('.selected').length, 1)
        eq_(li.find('a').attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id,
                      sort='downloads'))

    def test_search_category(self):
        # Ensure category got preserved in search term.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#search input[name=cat]').val(), str(self.cat.id))
