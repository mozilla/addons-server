import json

from django import test

import mock
from nose.tools import eq_
import test_utils

import amo
from amo.urlresolvers import reverse
from bandwagon.models import SyncedCollection
from discovery import views


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
                      "not-a-real-guid",
                      "yslow@yahoo-inc.com"]
        self.ids = [5299, 1843, 2464, 7661, 5369]
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

    def test_get_addon_ids(self):
        ids = set(views.get_addon_ids(self.guids))
        eq_(ids, set(self.ids))

    def test_get_synced_collection(self):
        # Get a fresh synced collection.
        c = views.get_synced_collection(self.ids, 'token')
        eq_(c.listed, False)
        eq_(c.type, amo.COLLECTION_SYNCHRONIZED)
        eq_(set(c.addons.values_list('id', flat=True)), set(self.ids))

        # Check that the token was set.
        eq_(c.token_set.get().token, 'token')

        # Make sure we get the same collection if we try again.
        next = views.get_synced_collection(self.ids, 'next')
        eq_(next.id, c.id)
        eq_(set(next.addons.values_list('id', flat=True)), set(self.ids))
        eq_(list(c.token_set.values_list('token', flat=True)),
            ['token', 'next'])

    def test_get_synced_collection_with_dupes(self):
        """It shouldn't happen, but make sure we handled synced dupes."""
        one = SyncedCollection.objects.create()
        one.set_addons(self.ids)
        two = SyncedCollection.objects.create()
        two.set_addons(self.ids)

        three = views.get_synced_collection(self.ids, 'token')
        assert one.addon_index == two.addon_index == three.addon_index

    @mock.patch('discovery.views.uuid.uuid4')
    def test_get_random_token(self, uuid_mock):
        uuid_mock.side_effect = ['two', 'one', 'one', 'one'].pop
        eq_(views.get_random_token(), 'one')
        views.get_synced_collection([], 'one')
        eq_(views.get_random_token(), 'two')
