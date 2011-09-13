from decimal import Decimal
import json

from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from market.models import Price
from stats.models import Contribution
from users.models import UserProfile

from django.utils import translation


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
