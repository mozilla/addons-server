import json

from nose.tools import eq_, ok_

import amo
import mkt

from addons.models import AddonCategory, Category
from mkt.api.base import list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.browse.tests.test_views import BrowseBase
from mkt.home.forms import Featured
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


class TestForm(amo.tests.TestCase):

    def lookup(self, region, device):
        form = Featured({'dev': device}, region=region)
        ok_(form.is_valid(), form.errors)
        return form.as_featured()

    def test_device(self):
        eq_(self.lookup(region=None, device='desktop'),
            {'mobile': False, 'gaia': False, 'tablet': False,
             'region': mkt.regions.WORLDWIDE, 'cat': None})

        eq_(self.lookup(region=None, device='android'),
            {'mobile': True, 'gaia': False, 'tablet': True,
             'region': mkt.regions.WORLDWIDE, 'cat': None})

        eq_(self.lookup(region=None, device='firefoxos'),
            {'mobile': True, 'gaia': True, 'tablet': False,
             'region': mkt.regions.WORLDWIDE, 'cat': None})

    def test_region(self):
        eq_(self.lookup(region=None, device=None)['region'],
            mkt.regions.WORLDWIDE)

        eq_(self.lookup(region=mkt.regions.US.slug, device=None)['region'],
            mkt.regions.US)


class TestAPI(BaseOAuth, BrowseBase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestAPI, self).setUp(api_name='home')
        BrowseBase.setUp(self)

        self.url = list_url('page')

    def test_has_cors(self):
        res = self.anon.get(self.url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')

    def test_response(self):
        cf1, cf2, hf = self.setup_featured()
        res = self.anon.get(self.url)
        content = json.loads(res.content)
        eq_(content['categories'][0]['slug'], u'lifestyle')
        eq_(content['featured'][0]['id'], u'%s' % hf.id)


class TestFeaturedHomeHandler(BaseOAuth):

    def setUp(self):
        super(TestFeaturedHomeHandler, self).setUp(api_name='home')
        self.list_url = list_url('featured')
        self.cat = Category.objects.create(name='awesome',
                                           type=amo.ADDON_WEBAPP,
                                           slug='awesome')

        # App, no category, worldwide region.
        self.app1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                          name='App 1')
        f1 = FeaturedApp.objects.create(app=self.app1, category=None)
        FeaturedAppRegion.objects.create(featured_app=f1,
                                         region=mkt.regions.WORLDWIDE.id)

        # App, with category, worldwide region. Mostly to ensure category
        # specific featured apps don't slip into the results.
        self.app2 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                          name='App 2')
        AddonCategory.objects.create(category=self.cat, addon=self.app2)
        f2 = FeaturedApp.objects.create(app=self.app2, category=self.cat)
        FeaturedAppRegion.objects.create(featured_app=f2,
                                         region=mkt.regions.WORLDWIDE.id)

        # App, no category, US region.
        self.app3 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
                                          name='App 3')
        f3 = FeaturedApp.objects.create(app=self.app3)
        FeaturedAppRegion.objects.create(featured_app=f3,
                                         region=mkt.regions.US.id)

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['get'])

    def test_has_cors(self):
        res = self.client.get(self.list_url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')

    def test_get_featured(self):
        res = self.anon.get(self.list_url)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['objects'][0]['slug'], self.app1.app_slug)

    def test_get_featured_region(self):
        # UK region should come up empty, so we backfill with worldwide.
        res = self.anon.get(self.list_url, data=dict(region='uk'))
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['objects'][0]['slug'], self.app1.app_slug)

        # US region should come have 1 plus worldwide.
        res = self.anon.get(self.list_url, data=dict(region='us'))
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        self.assertSetEqual([o['slug'] for o in data['objects']],
                            ['app-1', 'app-3'])

    def _get_category(self, data):
        res = self.anon.get(self.list_url, data=data)
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['meta']['total_count'], 1)
        # App2 is in the category.
        eq_(data['objects'][0]['slug'], self.app2.app_slug)

    def test_get_category(self):
        self._get_category({'category': self.cat.pk})

    def test_get_slug(self):
        self._get_category({'category': self.cat.slug})
