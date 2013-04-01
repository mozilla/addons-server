import json

from nose.tools import eq_

from mkt.api.base import list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.browse.tests.test_views import BrowseBase
from mkt.home.api import HomepageResource
from mkt.site.fixtures import fixture


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

    def test_lookup(self):
        lookup = HomepageResource().lookup_device
        eq_(lookup('desktop'),
            {'mobile': False, 'gaia': False, 'tablet': False})
        eq_(lookup('android'),
            {'mobile': True, 'gaia': False, 'tablet': True})
        eq_(lookup('firefoxos'),
            {'mobile': True, 'gaia': True, 'tablet': False})
        eq_(lookup('something-else'),
            {'mobile': False, 'gaia': False, 'tablet': False})
