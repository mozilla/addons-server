from decimal import Decimal
import json


import mock
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import AddonPremium, PreApprovalUser, Price
from stats.models import Contribution
from users.models import UserProfile

from django.utils import translation


class TestPremium(amo.tests.TestCase):
    fixtures = ['prices.json', 'base/addon_3615.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)
        self.addon = Addon.objects.get(pk=3615)

    def test_is_complete(self):
        ap = AddonPremium.objects.create(addon=self.addon)
        assert not ap.is_complete()
        ap.price = self.tier_one
        assert not ap.is_complete()
        ap.addon.paypal_id = 'asd'
        assert ap.is_complete()

    @mock.patch('paypal.should_ignore_paypal', lambda: False)
    def test_has_permissions_token(self):
        ap = AddonPremium.objects.create(addon=self.addon)
        assert not ap.has_permissions_token()
        ap.paypal_permissions_token = 'asd'
        assert ap.has_permissions_token()

    @mock.patch('paypal.should_ignore_paypal', lambda: True)
    def test_has_permissions_token_ignore(self):
        ap = AddonPremium.objects.create(addon=self.addon)
        assert ap.has_permissions_token()
        ap.paypal_permissions_token = 'asd'
        assert ap.has_permissions_token()

    @mock.patch('paypal.should_ignore_paypal', lambda: False)
    @mock.patch('paypal.check_refund_permission')
    def test_has_valid_permissions_token(self, check_refund_permission):
        ap = AddonPremium.objects.create(addon=self.addon)
        assert not ap.has_valid_permissions_token()
        check_refund_permission.return_value = True
        ap.paypal_permissions_token = 'some_token'
        assert ap.has_valid_permissions_token()

    @mock.patch('paypal.should_ignore_paypal', lambda: True)
    def test_has_valid_permissions_token_ignore(self):
        ap = AddonPremium.objects.create(addon=self.addon)
        assert ap.has_valid_permissions_token()
        ap.paypal_permissions_token = 'asd'
        assert ap.has_valid_permissions_token()


class TestPrice(amo.tests.TestCase):
    fixtures = ['prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)

    def test_currency(self):
        eq_(self.tier_one.pricecurrency_set.count(), 2)

    def test_get(self):
        eq_(Price.objects.get(pk=1).get_price(), Decimal('0.99'))

    def test_get_locale(self):
        translation.activate('fr')
        eq_(Price.objects.filter(pk=2)[0].get_price(), Decimal('1.99'))
        # If you are in France, you might still get US prices but at
        # least we'll format into French for you.
        eq_(Price.objects.filter(pk=2)[0].get_price_locale(), u'1,99\xa0$US')
        # In this case we have a currency so it's converted into Euro.
        eq_(Price.objects.filter(pk=1)[0].get_price_locale(),
            u'5,01\xa0\u20ac')

    def test_get_tier(self):
        translation.activate('en_CA')
        eq_(Price.objects.get(pk=1).get_price(), Decimal('3.01'))
        eq_(Price.objects.get(pk=1).get_price_locale(), u'$3.01')

    def test_get_tier_and_locale(self):
        translation.activate('pt_BR')
        eq_(Price.objects.get(pk=2).get_price(), Decimal('1.01'))
        eq_(Price.objects.get(pk=2).get_price_locale(), u'R$1,01')

    def test_fallback(self):
        translation.activate('foo')
        eq_(Price.objects.get(pk=1).get_price(), Decimal('0.99'))
        eq_(Price.objects.get(pk=1).get_price_locale(), u'$0.99')

    def test_transformer(self):
        prices = list(Price.objects.filter(pk=1))
        with self.assertNumQueries(0):
            eq_(prices[0].get_price_locale(), u'$0.99')


class TestContribution(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def create(self, type):
        Contribution.objects.create(type=type, addon=self.addon,
                                    user=self.user)

    def purchased(self):
        return (self.addon.addonpurchase_set
                          .filter(user=self.user, type=amo.CONTRIB_PURCHASE)
                          .exists())

    def type(self):
        return self.addon.addonpurchase_set.get(user=self.user).type

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
        eq_(self.type(), amo.CONTRIB_REFUND)

    def test_refund_and_purchase(self):
        # This refund does nothing, there was nothing there to refund.
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        assert self.purchased()
        eq_(self.type(), amo.CONTRIB_PURCHASE)

    def test_really_cant_decide(self):
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        self.create(amo.CONTRIB_PURCHASE)
        assert self.purchased()
        eq_(self.type(), amo.CONTRIB_PURCHASE)

    def test_purchase_and_chargeback(self):
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_CHARGEBACK)
        assert not self.purchased()
        eq_(self.type(), amo.CONTRIB_CHARGEBACK)

    def test_other_user(self):
        other = UserProfile.objects.get(email='admin@mozilla.com')
        Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                    addon=self.addon, user=other)
        self.create(amo.CONTRIB_PURCHASE)
        self.create(amo.CONTRIB_REFUND)
        eq_(self.addon.addonpurchase_set.filter(user=other).count(), 1)

    def test_user_installed(self):
        self.create(amo.CONTRIB_PURCHASE)
        eq_(self.user.installed_set.filter(addon=self.addon).count(), 1)

    def test_user_not_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(list(self.user.purchase_ids()), [])

    def test_user_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.addon.addonpurchase_set.create(user=self.user)
        eq_(list(self.user.purchase_ids()), [3615L])

    def test_user_refunded(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.addon.addonpurchase_set.create(user=self.user,
                                            type=amo.CONTRIB_REFUND)
        eq_(list(self.user.purchase_ids()), [])


class TestUserPreApproval(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = UserProfile.objects.get(pk=999)

    def test_get_preapproval(self):
        eq_(self.user.get_preapproval(), None)
        pre = PreApprovalUser.objects.create(user=self.user)
        eq_(self.user.get_preapproval(), pre)
