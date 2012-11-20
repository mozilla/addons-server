# -*- coding: utf8 -*-
import calendar
import json
from urllib import urlencode
import time

from django.db import connection
from django.conf import settings

import M2Crypto
import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from browserid.errors import ExpiredSignatureError
from services import verify
from services import utils
from mkt.receipts.utils import create_receipt
from mkt.webapps.models import Installed
from market.models import AddonPurchase
from users.models import UserProfile
from stats.models import Contribution


def get_response(data, status):
    response = mock.Mock()
    response.read.return_value = data
    response.getcode.return_value = status
    return response


sample = ('eyJqa3UiOiAiaHR0cHM6Ly9tYXJrZXRwbGFjZS1kZXYtY2RuL'
'mFsbGl6b20ub3JnL3B1YmxpY19rZXlzL3Rlc3Rfcm9vdF9wdWIuandrIiwgInR5cCI6ICJKV'
'1QiLCAiYWxnIjogIlJTMjU2In0.eyJwcm9kdWN0IjogeyJ1cmwiOiAiaHR0cDovL2Rla2tvc'
'3R1ZGlvcy5jb20iLCAic3RvcmVkYXRhIjogImlkPTM2Mzk4MiJ9LCAiaXNzIjogImh0dHBzO'
'i8vbWFya2V0cGxhY2UtZGV2LmFsbGl6b20ub3JnIiwgInZlcmlmeSI6ICJodHRwczovL3JlY'
'2VpcHRjaGVjay1tYXJrZXRwbGFjZS1kZXYuYWxsaXpvbS5vcmcvdmVyaWZ5LzM2Mzk4MiIsI'
'CJkZXRhaWwiOiAiaHR0cHM6Ly9tYXJrZXRwbGFjZS1kZXYuYWxsaXpvbS5vcmcvZW4tVVMvc'
'HVyY2hhc2VzLzM2Mzk4MiIsICJyZWlzc3VlIjogImh0dHBzOi8vbWFya2V0cGxhY2UtZGV2L'
'mFsbGl6b20ub3JnL2VuLVVTL2FwcC9zZWV2YW5zLXVuZGVyd29ybGQtYWR2ZW50dXIvcHVyY'
'2hhc2UvcmVpc3N1ZSIsICJ1c2VyIjogeyJ0eXBlIjogImRpcmVjdGVkLWlkZW50aWZpZXIiL'
'CAidmFsdWUiOiAiMjYzLTI3OGIwYTc3LWE5MGMtNDYyOC1iODQ3LWU3YTU0MzQ1YTMyMCJ9L'
'CAiZXhwIjogMTMzNTk5MDkwOSwgImlhdCI6IDEzMzUzODYxMDksICJ0eXAiOiAicHVyY2hhc'
'2UtcmVjZWlwdCIsICJuYmYiOiAxMzM1Mzg2MTA5fQ.ksPSozpX5ufHSdjrKGEUa9QC1tLh_t'
'a-xIkY18ZRwbmDqV05oCLdhzO6L1Gqzg8bCUg3cl_cBD9cKP23dvqfSwydeZlQL0jbBEUSIs'
'9EDd1_eIDOt_ifjm0D6YrTvfXuokRhD5ojhS6b8_fzAlWiQ_UWnyccaYE2eflR96hGXi-cJZ'
'9u6Fb9DNlgAK4xI4uLzYHxJJuY2N9yotcle0IzQGDBIooBKIns7FWC7J5mCdTJP4nil2rrMb'
'pprvfinNhfK5oYPWTPgc3NQNteBbK7XDoY2ZESXW66sYgG5jDMVnhTO2NXJmyDHuIrhiVWsf'
'xVjY54e0R4NlfjsQmM3wURxg')


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

    def get_decode(self, receipt, check_purchase=True):
        # Ensure that the verify code is using the test database cursor.
        v = verify.Verify(receipt, {})
        v.cursor = connection.cursor()
        return json.loads(v(check_purchase=check_purchase))

    @mock.patch.object(verify, 'decode_receipt')
    def get(self, receipt, decode_receipt, check_purchase=True):
        decode_receipt.return_value = receipt
        return self.get_decode('', check_purchase=check_purchase)

    def make_install(self):
        install = Installed.objects.create(addon=self.addon, user=self.user)
        install.update(uuid='some-uuid')
        return install

    def make_purchase(self):
        return AddonPurchase.objects.create(addon=self.addon, user=self.user)

    def make_contribution(self, type=amo.CONTRIB_PURCHASE):
        return Contribution.objects.create(addon=self.addon, user=self.user,
                                           type=type)

    @mock.patch.object(utils.settings, 'SIGNING_SERVER_ACTIVE', True)
    def test_invalid_receipt(self):
        eq_(self.get_decode('blah')['status'], 'invalid')

    def test_invalid_signature(self):
        eq_(self.get_decode('blah.blah.blah')['status'], 'invalid')

    def test_no_user(self):
        user_data = self.user_data.copy()
        del user_data['user']
        eq_(self.get(user_data)['status'], 'invalid')

    def test_no_addon(self):
        user_data = self.user_data.copy()
        del user_data['product']
        eq_(self.get(user_data)['status'], 'invalid')

    def test_user_type_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['type'] = 'nope'
        self.make_install()
        res = self.get(user_data)
        eq_(res['status'], 'invalid')

    def test_user_value_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['value'] = 'ugh'
        self.make_install()
        res = self.get(user_data)
        eq_(res['status'], 'invalid')

    def test_user_addon(self):
        self.make_install()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    def test_user_deleted(self):
        self.make_install()
        self.user.delete()
        res = self.get(self.user_data)
        eq_(res['status'], 'invalid')

    def test_user_anonymise(self):
        self.make_install()
        self.user.anonymize()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    @mock.patch('services.verify.sign')
    def test_expired(self, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_install()
        res = self.get(user_data)
        eq_(res['status'], 'expired')

    @mock.patch('services.verify.sign')
    def test_garbage_expired(self, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = 'a'
        self.make_install()
        res = self.get(user_data)
        eq_(res['status'], 'expired')

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_EXPIRED_SEND', True)
    @mock.patch('services.verify.sign')
    def test_expired_has_receipt(self, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_install()
        res = self.get(user_data)
        assert 'receipt' in res

    @mock.patch.object(utils.settings, 'SIGNING_SERVER_ACTIVE', True)
    @mock.patch('services.verify.receipts.certs.ReceiptVerifier.verify')
    def test_expired_cert(self, mthd):
        mthd.side_effect = ExpiredSignatureError
        assert 'typ' in verify.decode_receipt('.~' + sample)

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_EXPIRED_SEND', True)
    @mock.patch('services.verify.sign')
    def test_new_expiry(self, sign):
        user_data = self.user_data.copy()
        user_data['exp'] = old = calendar.timegm(time.gmtime()) - 10000
        self.make_install()
        sign.return_value = ''
        self.get(user_data)
        assert sign.call_args[0][0]['exp'] > old

    def test_expired_not_signed(self):
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 10000
        self.make_install()
        res = self.get(user_data)
        eq_(res['status'], 'expired')

    def test_premium_addon_not_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        res = self.get(self.user_data)
        eq_(res['status'], 'invalid')

    def test_premium_dont_check(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        res = self.get(self.user_data, check_purchase=False)
        eq_(res['status'], 'ok')

    def test_premium_addon_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        self.make_purchase()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    def test_premium_addon_contribution(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        # There's no purchase, but the last entry we have is a sale.
        self.make_contribution()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    def test_premium_addon_refund(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_install()
        purchase = self.make_purchase()
        for type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
            purchase.update(type=type)
            res = self.get(self.user_data)
            eq_(res['status'], 'refunded')

    def test_other_premiums(self):
        for k in (amo.ADDON_FREE, amo.ADDON_PREMIUM_INAPP,
                  amo.ADDON_FREE_INAPP, amo.ADDON_OTHER_INAPP):
            Installed.objects.all().delete()
            self.addon.update(premium_type=k)
            self.make_install()
            res = self.get(self.user_data)
            eq_(res['status'], 'ok')

    def test_product_wrong_store_data(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 123})}
        eq_(self.get(data)['status'], 'invalid')

    def test_product_wrong_type(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 3615})}
        eq_(self.get(data)['status'], 'ok')

    def test_product_ok_store_data(self):
        self.make_install()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 3615})}
        eq_(self.get(data)['status'], 'ok')

    def test_product_barf_store_data(self):
        self.make_install()
        for storedata in (urlencode({'id': 'NaN'}), 'NaN'):
            data = self.user_data.copy()
            data['product'] = {'url': 'http://f.com', 'storedata': storedata}
            eq_(self.get(data)['status'], 'invalid')

    def test_crack_receipt(self):
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = create_receipt(self.make_install().pk)
        result = verify.decode_receipt(receipt)
        eq_(result['typ'], u'purchase-receipt')

    @mock.patch('services.verify.settings')
    @mock.patch('services.verify.receipts.certs.ReceiptVerifier')
    def test_crack_receipt_new_called(self, trunion_verify, settings):
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        verify.decode_receipt('.~' + sample)
        assert trunion_verify.called

    def test_crack_borked_receipt(self):
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        receipt = create_receipt(self.make_install().pk)
        self.assertRaises(M2Crypto.RSA.RSAError, verify.decode_receipt,
                          receipt + 'x')

    @mock.patch.object(verify, 'decode_receipt')
    def get_headers(self, decode_receipt):
        decode_receipt.return_value = ''
        return verify.get_headers(verify.Verify('', mock.Mock()))

    def test_cross_domain(self):
        hdrs = self.get_headers()
        assert ('Access-Control-Allow-Origin', '*') in hdrs, (
                'No cross domain headers')
        assert ('Access-Control-Allow-Methods', 'POST') in hdrs, (
                'Allow POST only')

    def test_no_cache(self):
        hdrs = self.get_headers()
        assert ('Cache-Control', 'no-cache') in hdrs, 'No cache header needed'
