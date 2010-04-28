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
        response = self.client.post(self.url, "{{{",
                                    content_type='application/json')
        eq_(response.status_code, 400)

    def test_new_synced_collection(self):
        response = self.client.post(self.url, self.json,
                                    content_type='application/json')
        return
        """check that these addons are in the new collection
        [5299L, 1843L, 2464L, 7661L, 5369L]
        """

    def test_new_recommended_collection(self):
        """Check that the created collection has a recommended collection."""
        pass

    def test_duplicate_syncs(self):
        """Check that sending the same addons reuses an existing synced
        collection."""
        pass
