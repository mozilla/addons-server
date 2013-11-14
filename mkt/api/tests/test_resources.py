import json

from nose.tools import eq_
from django.core.urlresolvers import reverse

from mkt.api.tests.test_oauth import RestOAuth


class TestConfig(RestOAuth):

    def setUp(self):
        super(TestConfig, self).setUp()
        self.url = reverse('site-config')

    def testConfig(self):
        self.create_switch('allow-refund')
        res = self.anon.get(self.url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['settings']['SITE_URL'], 'http://testserver')
        eq_(data['flags']['allow-refund'], True)

    def test_cors(self):
        self.assertCORS(self.anon.get(self.url), 'get')
