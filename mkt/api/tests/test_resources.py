import json

from nose.tools import eq_

from mkt.api.tests.test_oauth import BaseOAuth
from mkt.api.base import get_url


class TestConfig(BaseOAuth):

    def setUp(self):
        super(TestConfig, self).setUp(api_name='services')
        self.url = get_url('config', pk='site')

    def test(self):
        self.create_switch('allow-refund')
        res = self.anon.get(self.url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['settings']['SITE_URL'], 'http://testserver')
        eq_(data['flags']['allow-refund'], True)

    def test_cors(self):
        self.assertCORS(self.anon.get(self.url), 'get')
