import datetime

from django.conf import settings

from nose.tools import eq_

from amo.tests import app_factory, mock_es
from amo.urlresolvers import reverse

import mkt
from mkt.browse.tests.test_views import BrowseBase
from mkt.webapps.models import Webapp
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


class TestHome(BrowseBase):

    def setUp(self):
        super(TestHome, self).setUp()
        self.url = reverse('home')
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    @mock_es
    def test_no_paypal_js(self):
        self.create_switch('enabled-paypal', active=False)
        resp = self.client.get(self.url)
        assert not settings.PAYPAL_JS_URL in resp.content, (
                    'When paypal is disabled, its JS lib should not load')

    @mock_es
    def test_load_paypal_js(self):
        self.create_switch('enabled-paypal')
        resp = self.client.get(self.url)
        assert settings.PAYPAL_JS_URL in resp.content, (
                    'When paypal is enabled, its JS lib should load')

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

        worldwide_apps = [app_factory().id for x in xrange(5)]
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

    def make_time_limited_feature(self):
        a = app_factory()
        fa = self.make_featured(app=a, category=None)
        fa.start_date = datetime.date(2012, 1, 1)
        fa.end_date = datetime.date(2012, 2, 1)
        fa.save()
        return a

    @mock_es
    def test_featured_time_excluded(self):
        a = self.make_time_limited_feature()
        for d in [datetime.date(2012, 1, 1),
                  datetime.date(2012, 1, 15),
                  datetime.date(2012, 2, 1)]:
            Webapp.now = staticmethod(lambda: d)
            eq_(self.get_pks('featured', self.url,  {'region': 'us'}),
                [a.id])
    @mock_es
    def test_featured_time_included(self):
        self.make_time_limited_feature()
        for d in [datetime.date(2011, 12, 15),
                  datetime.date(2012, 2, 2)]:
            Webapp.now = staticmethod(lambda: d)
            eq_(self.get_pks('featured', self.url, {'region': 'us'}), [])
