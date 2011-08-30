import json
import os

from django.conf import settings

import mock
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import AddonPurchase, Price, get_key
from stats.models import Contribution
from users.models import UserProfile
from webapps.models import Webapp

key = os.path.join(os.path.dirname(__file__), 'sample.key')


class TestPrice(amo.tests.TestCase):
    fixtures = ['prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)

    def test_currency(self):
        eq_(self.tier_one.pricecurrency_set.count(), 2)


class TestReceipt(amo.tests.TestCase):
    fixtures = ['base/users.json']

    def setUp(self):
        self.webapp = Webapp.objects.create(type=amo.ADDON_EXTENSION)
        self.user = UserProfile.objects.get(pk=999)
        self.other_user = UserProfile.objects.exclude(pk=999)[0]

    def test_no_receipt(self):
        ap = AddonPurchase.objects.create(user=self.user, addon=self.webapp)
        eq_(ap.receipt, '')

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY', 'rubbish')
    def test_get_key(self):
        self.assertRaises(IOError, get_key)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY', key)
    def create_receipt(self, user, webapp):
        self.webapp.update(type=amo.ADDON_WEBAPP,
                           manifest_url='http://somesite.com/')
        return AddonPurchase.objects.create(user=user, addon=webapp)

    def test_receipt(self):
        ap = self.create_receipt(self.user, self.webapp)
        assert ap.receipt.startswith('eyJhbGciOiAiSFMyNTY'), ap.receipt

    def test_receipt_different(self):
        ap = self.create_receipt(self.user, self.webapp)
        ap_other = self.create_receipt(self.other_user, self.webapp)
        assert ap.receipt != ap_other.receipt

    def test_addon(self):
        # An overall test of what's going on.
        self.create_receipt(self.user, self.webapp)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        assert self.webapp.has_purchased(self.user)
        assert not self.webapp.has_purchased(self.other_user)
        assert self.webapp.addonpurchase_set.all()[0].receipt


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


class TestContribution(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def create(self, type):
        Contribution.objects.create(type=type, addon=self.addon,
                                    user=self.user)

    def purchased(self):
        return self.addon.addonpurchase_set.filter(user=self.user).exists()

    def test_purchase(self):
        self.create(amo.CONTRIB_PURCHASE)
        assert self.purchased()

    def test_refund(self):
        self.create(amo.CONTRIB_REFUND)
        assert not self.purchased()

    def test_purchase_and_refund(self):
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        assert not self.purchased()

    def test_refund_and_purchase(self):
        # This refund does nothing, there was nothing there to refund.
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        assert self.purchased()

    def test_really_cant_decide(self):
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        assert self.purchased()

    def test_purchase_and_chargeback(self):
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_CHARGEBACK)
        assert not self.purchased()

    def test_other_user(self):
        other = UserProfile.objects.get(email='admin@mozilla.com')
        Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                    addon=self.addon, user=other)
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        eq_(self.addon.addonpurchase_set.filter(user=other).count(), 1)
