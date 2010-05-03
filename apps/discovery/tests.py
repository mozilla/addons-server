import json

from django import test

from nose.tools import eq_
import test_utils

from amo.urlresolvers import reverse
from addons.models import Addon


class RecsTest(test_utils.TestCase):
    fixtures = ['base/addons', 'base/category', 'base/featured']

    @classmethod
    def setup_class(cls):
        test.Client().get('/')

    def setUp(self):
        self.url = reverse('discovery.recs')
        self.guids = ["bettergcal@ginatrapani.org",
                      "firebug@software.joehewitt.com",
                      "foxyproxy@eric.h.jung",
                      "isreaditlater@ideashower.com",
                      "yslow@yahoo-inc.com"]
        self.json = json.dumps(self.guids)

    def test_get(self):
        """GET should find method not allowed."""
        response = self.client.get(self.url)
        eq_(response.status_code, 405)

    def test_empty_post_data(self):
        response = self.client.post(self.url)
        eq_(response.status_code, 400)

    def test_bad_post_data(self):
        response = self.client.post(self.url, "{]{",
                                    content_type='application/json')
        eq_(response.status_code, 400)
