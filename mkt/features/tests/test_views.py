import json

from nose.tools import eq_

from django.core.urlresolvers import reverse

from mkt.api.tests.test_oauth import RestOAuth
from mkt.constants import APP_FEATURES


class TestConfig(RestOAuth):

    def setUp(self):
        super(TestConfig, self).setUp()
        self.url = reverse('api-features-feature-list')

    def _test_response(self, res):
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data), len(APP_FEATURES))
        self.assertSetEqual(data.keys(),
                            [f.lower() for f in APP_FEATURES.keys()])
        for i, feature in enumerate(APP_FEATURES.items()):
            name = feature[0].lower()
            eq_(i + 1, data[name]['position'])

    def test_anon(self):
        res = self.anon.get(self.url)
        self._test_response(res)

    def test_authenticated(self):
        res = self.client.get(self.url)
        self._test_response(res)

    def test_post(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 405)
