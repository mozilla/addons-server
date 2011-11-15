# -*- coding: utf8 -*-
from django.db import connection

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from services import verify
from webapps.models import Installed
from market.models import AddonPurchase
from users.models import UserProfile
from stats.models import Contribution

import json
import mock


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
        for type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
            self.make_contribution(type=type)
            res = self.get(3615, self.user_data)
            eq_(res['status'], 'refunded')

    def test_crack_receipt(self):
        receipt = self.make_install().receipt
        result = verify.decode_receipt(receipt)
        eq_(result['typ'], u'purchase-receipt')
