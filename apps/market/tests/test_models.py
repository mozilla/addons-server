import datetime
from decimal import Decimal

from django.utils import translation

import mock
from nose.tools import eq_, ok_

import amo
import amo.tests
from addons.models import Addon, AddonUser
from constants.payments import PROVIDER_BANGO
from market.models import AddonPremium, Price, Refund
from mkt.constants import apps
from mkt.constants.regions import (ALL_REGION_IDS, BR, HU,
                                   SPAIN, US, RESTOFWORLD)
from stats.models import Contribution
from users.models import UserProfile


class TestPremium(amo.tests.TestCase):
    fixtures = ['market/prices.json', 'base/addon_3615.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)
        self.addon = Addon.objects.get(pk=3615)

    def test_is_complete(self):
        ap = AddonPremium(addon=self.addon)
        assert not ap.is_complete()
        ap.price = self.tier_one
        assert not ap.is_complete()
        ap.addon.paypal_id = 'asd'
        assert ap.is_complete()


class TestPrice(amo.tests.TestCase):
    fixtures = ['market/prices.json']

    def setUp(self):
        self.tier_one = Price.objects.get(pk=1)
        if hasattr(Price, '_currencies'):
            del Price._currencies  # needed to pick up fixtures.

    def test_active(self):
        eq_(Price.objects.count(), 2)
        eq_(Price.objects.active().count(), 1)

    def test_active_order(self):
        Price.objects.create(name='USD', price='0.00')
        Price.objects.create(name='USD', price='1.99')
        eq_(list(Price.objects.active().values_list('price', flat=True)),
            [Decimal('0.00'), Decimal('0.99'), Decimal('1.99')])

    def test_method_default_all(self):
        price = Price.objects.create(name='USD', price='0.00')
        eq_(price.method, 2)

    def test_method_specified(self):
        price = Price.objects.create(name='USD', price='0.99', method=0)
        eq_(price.method, 0)

    def test_currency(self):
        eq_(self.tier_one.pricecurrency_set.count(), 3)

    def test_get(self):
        eq_(Price.objects.get(pk=1).get_price(), Decimal('0.99'))

    def test_get_tier(self):
        translation.activate('en_CA')
        eq_(Price.objects.get(pk=1).get_price(), Decimal('0.99'))
        eq_(Price.objects.get(pk=1).get_price_locale(), u'US$0.99')

    def test_get_tier_and_locale(self):
        translation.activate('pt_BR')
        eq_(Price.objects.get(pk=2).get_price(), Decimal('1.99'))
        eq_(Price.objects.get(pk=2).get_price_locale(), u'US$1,99')

    def test_no_region(self):
        eq_(Price.objects.get(pk=2).get_price_locale(region=HU.id), None)

    def test_fallback(self):
        translation.activate('foo')
        eq_(Price.objects.get(pk=1).get_price(), Decimal('0.99'))
        eq_(Price.objects.get(pk=1).get_price_locale(), u'$0.99')

    def test_transformer(self):
        price = Price.objects.get(pk=1)
        price.get_price_locale()
        # Warm up Price._currencies.
        with self.assertNumQueries(0):
            eq_(price.get_price_locale(), u'$0.99')

    def test_get_tier_price(self):
        eq_(Price.objects.get(pk=2).get_price_locale(region=BR.id), 'R$1.01')

    def test_get_free_tier_price(self):
        price = self.make_price('0.00')
        eq_(price.get_price_locale(region=US.id), '$0.00')

    def test_euro_placement(self):
        with self.activate('en-us'):
            eq_(Price.objects.get(pk=2).get_price_locale(region=SPAIN.id),
                u'\u20ac0.50')
        with self.activate('es'):
            eq_(Price.objects.get(pk=2).get_price_locale(region=SPAIN.id),
                u'0,50\xa0\u20ac')

    def test_prices(self):
        currencies = Price.objects.get(pk=1).prices()
        eq_(len(currencies), 2)
        eq_(currencies[0]['currency'], 'PLN')

    def test_wrong_currency(self):
        bad = 4999
        ok_(bad not in ALL_REGION_IDS)
        ok_(not Price.objects.get(pk=1).get_price('foo', region=bad))

    def test_prices_provider(self):
        currencies = Price.objects.get(pk=1).prices(provider=PROVIDER_BANGO)
        eq_(len(currencies), 2)

    def test_region_ids_by_slug(self):
        eq_(Price.objects.get(pk=2).region_ids_by_slug(),
            (BR.id, SPAIN.id, RESTOFWORLD.id))


class TestPriceCurrencyChanges(amo.tests.TestCase):

    def setUp(self):
        self.addon = amo.tests.addon_factory()
        self.make_premium(self.addon)
        self.currency = self.addon.premium.price.pricecurrency_set.all()[0]

    @mock.patch('addons.tasks.index_objects')
    def test_save(self, index_objects):
        self.currency.save()
        eq_(index_objects.call_args[0][0], [self.addon.pk])

    @mock.patch('addons.tasks.index_objects')
    def test_delete(self, index_objects):
        self.currency.delete()
        eq_(index_objects.call_args[0][0], [self.addon.pk])


class ContributionMixin(object):

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def create(self, type):
        return Contribution.objects.create(type=type, addon=self.addon,
                                           user=self.user)

    def purchased(self):
        return (self.addon.addonpurchase_set
                          .filter(user=self.user, type=amo.CONTRIB_PURCHASE)
                          .exists())

    def type(self):
        return self.addon.addonpurchase_set.get(user=self.user).type


class TestContribution(ContributionMixin, amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

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

    def set_role(self, role):
        AddonUser.objects.create(addon=self.addon, user=self.user, role=role)
        self.create(amo.CONTRIB_PURCHASE)
        installed = self.user.installed_set.filter(addon=self.addon)
        eq_(installed.count(), 1)
        eq_(installed[0].install_type, apps.INSTALL_TYPE_DEVELOPER)

    def test_user_dev(self):
        self.set_role(amo.AUTHOR_ROLE_DEV)

    def test_user_owner(self):
        self.set_role(amo.AUTHOR_ROLE_OWNER)

    def test_user_installed_dev(self):
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

    def test_user_cache(self):
        # Tests that the purchase_ids caches.
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(list(self.user.purchase_ids()), [])
        self.create(amo.CONTRIB_PURCHASE)
        eq_(list(self.user.purchase_ids()), [3615L])
        # This caches.
        eq_(list(self.user.purchase_ids()), [3615L])
        self.create(amo.CONTRIB_REFUND)
        eq_(list(self.user.purchase_ids()), [])


class TestRefundContribution(ContributionMixin, amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestRefundContribution, self).setUp()
        self.contribution = self.create(amo.CONTRIB_PURCHASE)

    def do_refund(self, expected, status, refund_reason=None,
                  rejection_reason=None):
        """Checks that a refund is enqueued and contains the correct values."""
        self.contribution.enqueue_refund(status, self.user,
            refund_reason=refund_reason,
            rejection_reason=rejection_reason)
        expected.update(contribution=self.contribution, status=status)
        eq_(Refund.objects.count(), 1)
        refund = Refund.objects.filter(**expected)
        eq_(refund.exists(), True)
        return refund[0]

    def test_pending(self):
        reason = 'this is bloody bullocks, mate'
        expected = dict(refund_reason=reason,
                        requested__isnull=False,
                        approved=None,
                        declined=None)
        refund = self.do_refund(expected, amo.REFUND_PENDING, reason)
        self.assertCloseToNow(refund.requested)

    def test_pending_to_approved(self):
        reason = 'this is bloody bullocks, mate'
        expected = dict(refund_reason=reason,
                        requested__isnull=False,
                        approved=None,
                        declined=None)
        refund = self.do_refund(expected, amo.REFUND_PENDING, reason)
        self.assertCloseToNow(refund.requested)

        # Change `requested` date to some date in the past.
        requested_date = refund.requested - datetime.timedelta(hours=1)
        refund.requested = requested_date
        refund.save()

        expected = dict(refund_reason=reason,
                        requested__isnull=False,
                        approved__isnull=False,
                        declined=None)
        refund = self.do_refund(expected, amo.REFUND_APPROVED)
        eq_(refund.requested, requested_date,
            'Expected date `requested` to remain unchanged.')
        self.assertCloseToNow(refund.approved)

    def test_approved_instant(self):
        expected = dict(refund_reason='',
                        requested__isnull=False,
                        approved__isnull=False,
                        declined=None)
        refund = self.do_refund(expected, amo.REFUND_APPROVED_INSTANT)
        self.assertCloseToNow(refund.requested)
        self.assertCloseToNow(refund.approved)

    def test_pending_to_declined(self):
        refund_reason = 'please, bro'
        rejection_reason = 'sorry, brah'

        expected = dict(refund_reason=refund_reason,
                        rejection_reason='',
                        requested__isnull=False,
                        approved=None,
                        declined=None)
        refund = self.do_refund(expected, amo.REFUND_PENDING, refund_reason)
        self.assertCloseToNow(refund.requested)

        requested_date = refund.requested - datetime.timedelta(hours=1)
        refund.requested = requested_date
        refund.save()

        expected = dict(refund_reason=refund_reason,
                        rejection_reason=rejection_reason,
                        requested__isnull=False,
                        approved=None,
                        declined__isnull=False)
        refund = self.do_refund(expected, amo.REFUND_DECLINED,
                                rejection_reason=rejection_reason)
        eq_(refund.requested, requested_date,
            'Expected date `requested` to remain unchanged.')
        self.assertCloseToNow(refund.declined)


class TestRefundManager(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.expected = {}
        for status in amo.REFUND_STATUSES.keys():
            c = Contribution.objects.create(addon=self.addon, user=self.user,
                                            type=amo.CONTRIB_PURCHASE)
            self.expected[status] = Refund.objects.create(contribution=c,
                                                          status=status,
                                                          user=self.user)

    def test_all(self):
        eq_(sorted(Refund.objects.values_list('id', flat=True)),
            sorted(e.id for e in self.expected.values()))

    def test_pending(self):
        eq_(list(Refund.objects.pending(self.addon)),
            [self.expected[amo.REFUND_PENDING]])

    def test_approved(self):
        eq_(list(Refund.objects.approved(self.addon)),
            [self.expected[amo.REFUND_APPROVED]])

    def test_instant(self):
        eq_(list(Refund.objects.instant(self.addon)),
            [self.expected[amo.REFUND_APPROVED_INSTANT]])

    def test_declined(self):
        eq_(list(Refund.objects.declined(self.addon)),
            [self.expected[amo.REFUND_DECLINED]])

    def test_by_addon(self):
        other = Addon.objects.create(type=amo.ADDON_WEBAPP)
        c = Contribution.objects.create(addon=other, user=self.user,
                                        type=amo.CONTRIB_PURCHASE)
        ref = Refund.objects.create(contribution=c, status=amo.REFUND_DECLINED,
                                    user=self.user)

        declined = Refund.objects.filter(status=amo.REFUND_DECLINED)
        eq_(sorted(r.id for r in declined),
            sorted(r.id for r in [self.expected[amo.REFUND_DECLINED], ref]))

        eq_(sorted(r.id for r in Refund.objects.by_addon(addon=self.addon)),
            sorted(r.id for r in self.expected.values()))
        eq_(list(Refund.objects.by_addon(addon=other)), [ref])
