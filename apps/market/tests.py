import json

from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from market.models import Price
from users.models import UserProfile


class TestPrice(amo.tests.TestCase):
    fixtures = ['prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)

    def test_currency(self):
        eq_(self.tier_one.pricecurrency_set.count(), 2)


class TestAddonPurchase(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(type=amo.ADDON_WEBAPP)
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('api.market.verify', args=[self.addon.slug])

    def test_anonymous(self):
        eq_(self.client.get(self.url).status_code, 302)

    def test_wrong_type(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.update(type=amo.ADDON_EXTENSION)
        res = self.client.get(self.url)
        eq_(res.status_code, 400)

    def test_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')

    def test_logged_in_ok(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'ok')

    def test_logged_in_other(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')
