from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from addons.models import AddonCategory, Category
from amo.tests import app_factory, mock_es
from amo.urlresolvers import reverse

import mkt
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp
from mkt.zadmin.models import FeaturedAppRegion


class TestHome(amo.tests.ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                           type=amo.ADDON_WEBAPP)
        self.url = reverse('home')
        self.webapp = Webapp.objects.get(id=337141)
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        self.webapp.save()
        self.refresh()

    def get_pks(self, key, url, data=None):
        r = self.client.get(url, data or {})
        eq_(r.status_code, 200)
        return sorted(x.id for x in r.context[key])

    def setup_featured(self, num=3):
        # Category featured.
        a = amo.tests.app_factory()
        self.make_featured(app=a, category=self.cat)

        b = amo.tests.app_factory()
        self.make_featured(app=b, category=self.cat)

        # Home featured.
        c = amo.tests.app_factory()
        self.make_featured(app=c, category=None)
        # Make this app compatible on only desktop.
        c.addondevicetype_set.create(device_type=amo.DEVICE_DESKTOP.id)

        if num == 4:
            d = amo.tests.app_factory()
            self.make_featured(app=d, category=None)
            # Make this app compatible on only mobile.
            d.addondevicetype_set.create(device_type=amo.DEVICE_MOBILE.id)
            return a, b, c, d
        else:
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

        # Popular for this category.
        a = amo.tests.app_factory()
        AddonCategory.objects.create(addon=a, category=self.cat)
        a.save()

        # Popular and category featured and home featured.
        self.make_featured(app=self.webapp, category=self.cat)
        self.make_featured(app=self.webapp, category=None)

        self.refresh()

        return a

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

    @mock_es
    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'home/home.html')

    def test_featured_src(self):
        _, _, app = self.setup_featured()
        r = self.client.get(self.url)
        eq_(pq(r.content)('.mkt-tile').attr('href'),
            app.get_detail_url() + '?src=mkt-home')

    def test_tile_no_rating_link(self):
        r = self.client.get(self.url)
        assert not pq(r.content)('.mkt-tile .rating_link')

    @mock_es
    def test_featured_region_exclusions(self):
        self._test_featured_region_exclusions()

    def test_popular(self):
        self._test_popular()

    def test_popular_region_exclusions(self):
        self._test_popular_region_exclusions()

    def make_time_limited_feature(self, start, end):
        a = app_factory()
        fa = self.make_featured(app=a, category=None)
        fa.start_date = start
        fa.end_date = end
        fa.save()
        return a

    @mock_es
    def test_featured_time_excluded(self):
        # Start boundary.
        a1 = self.make_time_limited_feature(self.days_ago(10),
                                            self.days_ago(-1))
        eq_(self.get_pks('featured', self.url, {'region': 'us'}), [a1.id])
        # End boundary.
        a2 = self.make_time_limited_feature(self.days_ago(1),
                                            self.days_ago(-10))
        eq_(self.get_pks('featured', self.url, {'region': 'us'}), [a1.id,
                                                                   a2.id])

    @mock_es
    def test_featured_time_included(self):
        self.make_time_limited_feature(self.days_ago(10), self.days_ago(5))
        eq_(self.get_pks('featured', self.url, {'region': 'us'}), [])
