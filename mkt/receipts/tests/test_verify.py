# -*- coding: utf8 -*-
import calendar
import json
import time
from urllib import urlencode

from django.db import connection
from django.conf import settings

import jwt
import M2Crypto
import mock
from browserid.errors import ExpiredSignatureError
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo
import amo.tests
from addons.models import Addon
from services import utils, verify
from mkt.receipts.utils import create_receipt
from mkt.site.fixtures import fixture
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
@mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_URL', 'http://foo.com')
class TestVerify(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999')

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.user_data = {'user': {'type': 'directed-identifier',
                                   'value': 'some-uuid'},
                          'product': {'url': 'http://f.com',
                                      'storedata': urlencode({'id': 337141})},
                          'verify': 'https://foo.com/verifyme/',
                          'exp': calendar.timegm(time.gmtime()) + 1000,
                          'typ': 'purchase-receipt'}

    def get_decode(self, receipt, check_purchase=True):
        # Ensure that the verify code is using the test database cursor.
        v = verify.Verify(receipt, RequestFactory().get('/verifyme/').META)
        v.cursor = connection.cursor()
        name = 'check_full' if check_purchase else 'check_without_purchase'
        return json.loads(getattr(v, name)())

    @mock.patch.object(verify, 'decode_receipt')
    def get(self, receipt, decode_receipt, check_purchase=True):
        decode_receipt.return_value = receipt
        return self.get_decode('', check_purchase=check_purchase)

    def make_purchase(self):
        return AddonPurchase.objects.create(addon=self.addon, user=self.user,
                                            uuid='some-uuid')

    def make_contribution(self, type=amo.CONTRIB_PURCHASE):
        cont = Contribution.objects.create(addon=self.addon, user=self.user,
                                           type=type)
        # This was created by the contribution, but we need to tweak
        # the uuid to ensure its correct.
        AddonPurchase.objects.get().update(uuid='some-uuid')
        return cont

    def get_uuid(self):
        return self.make_purchase().uuid

    @mock.patch.object(utils.settings, 'SIGNING_SERVER_ACTIVE', True)
    def test_invalid_receipt(self):
        eq_(self.get_decode('blah')['status'], 'invalid')

    def test_invalid_signature(self):
        eq_(self.get_decode('blah.blah.blah')['status'], 'invalid')

    @mock.patch('services.verify.receipt_cef.log')
    def test_no_user(self, log):
        user_data = self.user_data.copy()
        del user_data['user']
        res = self.get(user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'NO_DIRECTED_IDENTIFIER')
        ok_(log.called)

    def test_no_addon(self):
        user_data = self.user_data.copy()
        del user_data['product']
        res = self.get(user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'WRONG_STOREDATA')

    def test_user_type_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['type'] = 'nope'
        res = self.get(user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'NO_DIRECTED_IDENTIFIER')

    def test_type(self):
        user_data = self.user_data.copy()
        user_data['typ'] = 'anything'
        res = self.get(user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'WRONG_TYPE')

    def test_user_incorrect(self):
        user_data = self.user_data.copy()
        user_data['user']['value'] = 'ugh'
        res = self.get(user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'NO_PURCHASE')

    def test_user_deleted(self):
        self.user.delete()
        res = self.get(self.user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'NO_PURCHASE')

    def test_user_anonymise(self):
        #self.user.anonymize()
        self.make_purchase()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    @mock.patch('services.verify.sign')
    @mock.patch('services.verify.receipt_cef.log')
    def test_expired(self, log, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_purchase()
        res = self.get(user_data)
        eq_(res['status'], 'expired')
        ok_(log.called)

    @mock.patch('services.verify.sign')
    def test_garbage_expired(self, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = 'a'
        self.make_purchase()
        res = self.get(user_data)
        eq_(res['status'], 'expired')

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_EXPIRED_SEND', True)
    @mock.patch('services.verify.sign')
    def test_expired_has_receipt(self, sign):
        sign.return_value = ''
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 1000
        self.make_purchase()
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
        self.make_purchase()
        sign.return_value = ''
        self.get(user_data)
        assert sign.call_args[0][0]['exp'] > old

    def test_expired_not_signed(self):
        user_data = self.user_data.copy()
        user_data['exp'] = calendar.timegm(time.gmtime()) - 10000
        self.make_purchase()
        res = self.get(user_data)
        eq_(res['status'], 'expired')

    def test_premium_addon_not_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        res = self.get(self.user_data)
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'NO_PURCHASE')

    def test_premium_dont_check(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        res = self.get(self.user_data, check_purchase=False)
        # Because the receipt is the wrong type for skipping purchase.
        eq_(res['status'], 'invalid')
        eq_(res['reason'], 'WRONG_TYPE')

    @mock.patch.object(utils.settings, 'DOMAIN', 'foo.com')
    def test_premium_dont_check_properly(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        user_data = self.user_data.copy()
        user_data['typ'] = 'developer-receipt'
        res = self.get(user_data, check_purchase=False)
        eq_(res['status'], 'ok')

    def test_premium_addon_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.make_purchase()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    def test_premium_addon_contribution(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        # There's no purchase, but the last entry we have is a sale.
        self.make_contribution()
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    @mock.patch('services.verify.receipt_cef.log')
    def test_premium_addon_refund(self, log):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        purchase = self.make_purchase()
        for type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
            purchase.update(type=type)
            res = self.get(self.user_data)
            eq_(res['status'], 'refunded')
        eq_(log.call_count, 2)

    def test_premium_no_charge(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        purchase = self.make_purchase()
        purchase.update(type=amo.CONTRIB_NO_CHARGE)
        res = self.get(self.user_data)
        eq_(res['status'], 'ok')

    def test_other_premiums(self):
        self.make_purchase()
        for k in (amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP):
            self.addon.update(premium_type=k)
            res = self.get(self.user_data)
            eq_(res['status'], 'ok')

    def test_product_wrong_store_data(self):
        self.make_purchase()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 123})}
        eq_(self.get(data)['status'], 'invalid')

    def test_product_ok_store_data(self):
        self.make_purchase()
        data = self.user_data.copy()
        data['product'] = {'url': 'http://f.com',
                           'storedata': urlencode({'id': 337141})}
        eq_(self.get(data)['status'], 'ok')

    def test_product_barf_store_data(self):
        self.make_purchase()
        for storedata in (urlencode({'id': 'NaN'}), 'NaN'):
            data = self.user_data.copy()
            data['product'] = {'url': 'http://f.com', 'storedata': storedata}
            res = self.get(data)
            eq_(res['status'], 'invalid')
            eq_(res['reason'], 'WRONG_STOREDATA')

    def test_crack_receipt(self):
        # Check that we can decode our receipt and get a dictionary back.
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://a.com')
        purchase = self.make_purchase()
        receipt = create_receipt(purchase.addon, purchase.user, purchase.uuid)
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
        purchase = self.make_purchase()
        receipt = create_receipt(purchase.addon, purchase.user, purchase.uuid)
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


class TestBase(amo.tests.TestCase):

    def create(self, data, request=None):
        stuff = {'user': {'type': 'directed-identifier'}}
        stuff.update(data)
        key = jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
        receipt = jwt.encode(stuff, key, u'RS512')
        v = verify.Verify(receipt, request)
        v.decoded = v.decode()
        return v


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestType(TestBase):

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    def test_no_type(self):
        self.create({'typ': 'test-receipt'}).check_type('test-receipt')

    def test_wrong_type(self):
        with self.assertRaises(verify.InvalidReceipt):
            self.create({}).check_type('test-receipt')

    def test_test_type(self):
        sample = {'typ': 'test-receipt'}
        with self.assertRaises(verify.InvalidReceipt):
            self.create(sample).check_type('blargh')


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
@mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestURL(TestBase):

    def setUp(self):
        self.req = RequestFactory().post('/foo').META

    def test_wrong_domain(self):
        sample = {'verify': 'https://foo.com'}
        with self.assertRaises(verify.InvalidReceipt) as err:
            self.create(sample, request=self.req).check_url('f.com')
        eq_(str(err.exception), 'WRONG_DOMAIN')

    def test_wrong_path(self):
        sample = {'verify': 'https://f.com/bar'}
        with self.assertRaises(verify.InvalidReceipt) as err:
            self.create(sample, request=self.req).check_url('f.com')
        eq_(str(err.exception), 'WRONG_PATH')

    @mock.patch.object(utils.settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    def test_good(self):
        sample = {'verify': 'https://f.com/foo'}
        self.create(sample, request=self.req).check_url('f.com')


class TestServices(amo.tests.TestCase):

    def test_wrong_settings(self):
        with self.settings(SIGNING_SERVER_ACTIVE=''):
            eq_(verify.status_check({})[0], 500)
