from nose.tools import eq_

from amo.tests import app_factory, mock_es
from amo.urlresolvers import reverse

import mkt
from mkt.browse.tests.test_views import BrowseBase
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


class TestHome(BrowseBase):

    def setUp(self):
        super(TestHome, self).setUp()
        self.url = reverse('home')
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    @mock_es
    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'home/home.html')

    @mock_es
    def test_featured(self):
        self._test_featured()

    @mock_es
    def test_featured_region_exclusions(self):
        self._test_featured_region_exclusions()

    @mock_es
    def test_featured_fallback_to_worldwide(self):
        a, b, c = self.setup_featured()

        worldwide_apps = [app_factory().id for x in xrange(6)]
        for app in worldwide_apps:
            fa = FeaturedApp.objects.create(app_id=app, category=None)
            FeaturedAppRegion.objects.create(featured_app=fa,
                region=mkt.regions.WORLDWIDE.id)

        # In US: 1 US-featured app + 5 Worldwide-featured app.
        # Elsewhere: 6 Worldwide-featured apps.
        for region in mkt.regions.REGIONS_DICT:
            if region == 'us':
                expected = [c.id] + worldwide_apps[:5]
            else:
                expected = worldwide_apps
            eq_(self.get_pks('featured', self.url, {'region': region}),
                expected)

    def test_popular(self):
        self._test_popular()

    def test_popular_region_exclusions(self):
        self._test_popular_region_exclusions()
