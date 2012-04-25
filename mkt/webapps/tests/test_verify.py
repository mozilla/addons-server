# -*- coding: utf8 -*-
import calendar
import json
from urllib import urlencode
import time

from django.db import connection
from django.conf import settings

import M2Crypto
import mock
from nose import SkipTest
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from services import verify
from services import utils
from mkt.webapps.models import create_receipt, Installed
from market.models import AddonPurchase
from users.models import UserProfile
from stats.models import Contribution


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
        self.user_data = {'user': {'type': 'directed-identifier',
                                   'value': 'some-uuid'},
                          'product': {'url': 'http://f.com',
                                      'storedata': urlencode({'id': 3615})},
                          'exp': calendar.timegm(time.gmtime()) + 1000}

    def get_decode(self, addon_id, receipt):
        # Ensure that the verify code is using the test database cursor.
        v = verify.Verify(addon_id, receipt, {})
        v.cursor = connection.cursor()
        return json.loads(v())

    @mock.patch.object(verify, 'decode_receipt')
    def get(self, addon_id, receipt, decode_receipt):
        decode_receipt.return_value = receipt
        return self.get_decode(addon_id, '')

    def make_install(self):
        install = Installed.objects.create(addon=self.addon, user=self.user)
        install.update(uuid='some-uuid')
        return install

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
        user_data = self.user_data.copy()
        del user_data['user']
        eq_(self.get(0, user_data)['status'], 'invalid')

    def test_no_addon(self):
        user_data = self.user_data.copy()
        del user_data['product']
        eq_(self.get(0, user_data)['status'], 'invalid')

    def test_user_type_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['type'] = 'nope'
        self.make_install()
        res = self.get(3615, user_data)
        eq_(res['status'], 'invalid')

    def test_user_value_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['value'] = 'ugh'
        self.make_install()
        res = self.get(3615, user_data)
        eq_(res['status'], 'invalid')

    def test_user_addon(self):
        self.make_install()
        res = self.get(3615, self.user_data)
        eq_(res['status'], 'ok')

    def test_expired(self):
        raise SkipTest
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_install()
        res = self.get(3615, user_data)
        eq_(res['status'], 'expired')

    def test_garbage_expired(self):
        raise SkipTest
        user_data = self.user_data.copy()
        user_data['exp'] = 'a'
        self.make_install()
        res = self.get(3615, user_data)
        eq_(res['status'], 'expired')

    def test_expired_has_receipt(self):
        raise SkipTest
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_install()
        res = self.get(3615, user_data)
        assert 'receipt' in res

    @mock.patch('services.verify.sign')
    def test_new_expiry(self, sign):
        user_data = self.user_data.copy()
        user_data['exp'] = old = calendar.timegm(time.gmtime()) - 10000
        self.make_install()
        sign.return_value = ''
        self.get(3615, user_data)
        assert sign.call_args[0][0]['exp'] > old

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

    def test_other_premiums(self):
        for k in (amo.ADDON_FREE, amo.ADDON_PREMIUM_INAPP,
                  amo.ADDON_FREE_INAPP, amo.ADDON_PREMIUM_OTHER):
            Installed.objects.all().delete()
            self.addon.update(premium_type=k)
            self.make_install()
            res = self.get(3615, self.user_data)
            eq_(res['status'], 'ok')

    def test_product_wrong_store_data(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 123})}
        eq_(self.get(3615, data)['status'], 'invalid')

    def test_product_wrong_type(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 3615})}
        eq_(self.get('3615', data)['status'], 'ok')

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

    def test_crack_receipt(self):
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = create_receipt(self.make_install().pk)
        result = verify.decode_receipt(receipt)
        eq_(result['typ'], u'purchase-receipt')

    @mock.patch('services.verify.settings')
    def test_crack_receipt_new(self, settings):
        raise SkipTest
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = create_receipt(self.make_install().pk)
        # This is just temporary until decoding this happens.
        self.assertRaises(NotImplementedError, verify.decode_receipt, receipt)

    def test_crack_borked_receipt(self):
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = create_receipt(self.make_install().pk)
        self.assertRaises(M2Crypto.RSA.RSAError, verify.decode_receipt,
                          receipt + 'x')

    @mock.patch.object(verify, 'decode_receipt')
    def get_headers(self, decode_receipt):
        decode_receipt.return_value = ''
        return verify.Verify(3615, '', mock.Mock()).get_headers(1)

    def test_cross_domain(self):
        hdrs = self.get_headers()
        assert ('Access-Control-Allow-Origin', '*') in hdrs, (
                'No cross domain headers')
        assert ('Access-Control-Allow-Methods', 'POST') in hdrs, (
                'Allow POST only')

    def test_no_cache(self):
        hdrs = self.get_headers()
        assert ('Cache-Control', 'no-cache') in hdrs, 'No cache header needed'
