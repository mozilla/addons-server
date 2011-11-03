from decimal import Decimal
import json


import mock
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import AddonPremium, Price
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


class ReceiptCase(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(type=amo.ADDON_WEBAPP,
                          manifest_url='http://cbc.ca/manifest')
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('api.market.verify', args=[self.addon.slug])


@mock.patch('addons.models.Addon.is_premium', lambda x: True)
class TestAddonReceipt(ReceiptCase):

    def test_anonymous(self):
        eq_(self.client.get(self.url).status_code, 302)

    def test_wrong_type(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.update(type=amo.ADDON_EXTENSION)
        res = self.client.get(self.url)
        eq_(res.status_code, 400)

    def test_logged_in(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')

    def test_logged_in_ok(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'ok')

    def test_logged_in_other(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.client.login(username='admin@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')

    def test_user_not_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(list(self.user.purchase_ids()), [])

    def test_user_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.addon.addonpurchase_set.create(user=self.user)
        eq_(list(self.user.purchase_ids()), [3615L])


@mock.patch('addons.models.Addon.is_premium', lambda x: False)
class TestAddonReceiptFree(ReceiptCase):

    def test_free_install(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.get_or_create_install(self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'ok')

    def test_free_no_install(self):
        self.client.login(username='regular@mozilla.com', password='password')
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
