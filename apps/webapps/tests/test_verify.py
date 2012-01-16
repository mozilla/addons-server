# -*- coding: utf8 -*-
from django.db import connection
from django.conf import settings
from urllib import urlencode

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from services import verify
from services import utils
from webapps.models import Installed
from market.models import AddonPurchase
from users.models import UserProfile
from stats.models import Contribution

import json
import M2Crypto
import mock


# There are two "different" settings files that need to be patched,
# even though they are the same file.
@mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestVerify(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.user_data = {'user': {'value': self.user.email}}

    def get_decode(self, addon_id, receipt):
        # Ensure that the verify code is using the test database cursor.
        v = verify.Verify(addon_id, receipt)
        v.cursor = connection.cursor()
        return json.loads(v())

    @mock.patch.object(verify, 'decode_receipt')
    def get(self, addon_id, receipt, decode_receipt):
        decode_receipt.return_value = receipt
        return self.get_decode(addon_id, '')

    def make_install(self):
        return Installed.objects.create(addon=self.addon, user=self.user)

    def make_purchase(self):
        return AddonPurchase.objects.create(addon=self.addon, user=self.user)

    def make_contribution(self, type=amo.CONTRIB_PURCHASE):
        return Contribution.objects.create(addon=self.addon, user=self.user,
                                           type=type)

    def test_invalid_receipt(self):
        eq_(self.get_decode(1, 'blah')['status'], 'invalid')

    def test_invalid_signature(self):
        eq_(self.get_decode(1, 'blah.blah.blah')['status'], 'invalid')

    def test_no_user(self):
        eq_(self.get(1, {})['status'], 'invalid')

    def test_no_addon(self):
        eq_(self.get(0, {'user': {'value': 'a@a.com'}})['status'], 'invalid')

    def test_user_addon(self):
        self.make_install()
        res = self.get(3615, self.user_data)
        eq_(res['status'], 'ok')
        eq_(res['receipt'], self.user_data)

    def test_premium_addon_not_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        res = self.get(3615, self.user_data)
        eq_(res['status'], 'invalid')

    def test_premium_addon_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        self.make_purchase()
        res = self.get(3615, self.user_data)
        eq_(res['status'], 'ok')

    def test_premium_addon_contribution(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        # There's no purchase, but the last entry we have is a sale.
        self.make_contribution()
        res = self.get(3615, self.user_data)
        eq_(res['status'], 'ok')

    def test_premium_addon_refund(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        purchase = self.make_purchase()
        for type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
            purchase.update(type=type)
            res = self.get(3615, self.user_data)
            eq_(res['status'], 'refunded')

    def test_product_wrong_store_data(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 123})}
        eq_(self.get(3615, data)['status'], 'invalid')

    def test_product_ok_store_data(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 3615})}
        eq_(self.get(3615, data)['status'], 'ok')

    def test_product_barf_store_data(self):
        self.make_install()
        for storedata in (urlencode({'id': 'NaN'}), 'NaN'):
            data = self.user_data.copy()
            data['product'] = {'url': 'http://f.com', 'storedata': storedata}
            eq_(self.get(3615, data)['status'], 'invalid')

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_REQUIRE_STOREDATA',
                       True)
    def test_product_old_store_data_fails(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = 'http://f.com'
        eq_(self.get(3615, data)['status'], 'invalid')

    def test_crack_receipt(self):
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = self.make_install().receipt
        result = verify.decode_receipt(receipt)
        eq_(result['typ'], u'purchase-receipt')

    def test_crack_borked_receipt(self):
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = self.make_install().receipt
        self.assertRaises(M2Crypto.RSA.RSAError, verify.decode_receipt,
                          receipt + 'x')

    @mock.patch.object(verify, 'decode_receipt')
    def get_headers(self, decode_receipt):
        decode_receipt.return_value = ''
        return verify.Verify(3615, '').get_headers(1)

    def test_cross_domain(self):
        hdrs = self.get_headers()
        assert ('Access-Control-Allow-Origin', '*') in hdrs, (
                'No cross domain headers')
        assert ('Access-Control-Allow-Methods', 'POST') in hdrs, (
                'Allow POST only')

    def test_no_cache(self):
        hdrs = self.get_headers()
        assert ('Cache-Control', 'no-cache') in hdrs, 'No cache header needed'
