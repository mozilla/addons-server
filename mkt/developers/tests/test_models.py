from datetime import datetime, timedelta

import fudge
from nose.tools import eq_
from mock import Mock, patch

import amo
import amo.tests
from addons.models import Addon
from market.models import AddonPremium, Price
from users.models import UserProfile

from mkt.developers.models import (ActivityLog, AddonPaymentAccount,
                                   PaymentAccount)
from mkt.site.fixtures import fixture


class TestActivityLogCount(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        now = datetime.now()
        bom = datetime(now.year, now.month, 1)
        self.lm = bom - timedelta(days=1)
        self.user = UserProfile.objects.filter()[0]
        amo.set_user(self.user)

    def test_not_review_count(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_review_count(self):
        amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_review_count_few(self):
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.monthly_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_review_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        eq_(len(ActivityLog.objects.monthly_reviews()), 0)

    def test_not_total(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.total_reviews()), 0)

    def test_total_few(self):
        for x in range(0, 5):
            amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 5)

    def test_total_last_month(self):
        log = amo.log(amo.LOG['APPROVE_VERSION'], Addon.objects.get())
        log.update(created=self.lm)
        result = ActivityLog.objects.total_reviews()
        eq_(len(result), 1)
        eq_(result[0]['approval_count'], 1)
        eq_(result[0]['user'], self.user.pk)

    def test_log_admin(self):
        amo.log(amo.LOG['OBJECT_EDITED'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 1)
        eq_(len(ActivityLog.objects.for_developer()), 0)

    def test_log_not_admin(self):
        amo.log(amo.LOG['EDIT_VERSION'], Addon.objects.get())
        eq_(len(ActivityLog.objects.admin_events()), 0)
        eq_(len(ActivityLog.objects.for_developer()), 1)


class TestPaymentAccount(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999')

    def setUp(self):
        self.user = UserProfile.objects.filter()[0]

    @patch('mkt.developers.models.client')
    @patch('mkt.developers.models.SolitudeSeller.create')
    def test_create_bango(self, solselc, client):
        solselc.return_value = Mock(resource_uri='selluri')
        client.post_package.return_value = {'resource_uri': 'zipzap'}

        res = PaymentAccount.create_bango(
            self.user, {'account_name': 'Test Account'})
        eq_(res.name, 'Test Account')
        eq_(res.user, self.user)
        eq_(res.seller_uri, 'selluri')
        eq_(res.uri, 'zipzap')

        client.post_package.assert_called_with(
            data={'supportEmailAddress': 'support@example.com',
                  'paypalEmailAddress': 'nobody@example.com',
                  'seller': 'selluri'})

        client.post_bank_details.assert_called_with(
            data={'seller_bango': 'zipzap'})

    def test_cancel(self):
        res = PaymentAccount.objects.create(
            name='asdf', user=self.user, uri='foo')

        addon = Addon.objects.get()
        apa = AddonPaymentAccount.objects.create(
            addon=addon, provider='bango', account_uri='foo',
            product_uri='bpruri', set_price=12345)

        res.cancel()
        assert res.inactive
        assert not AddonPaymentAccount.objects.exists()


class TestAddonPaymentAccount(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999') + ['market/prices']

    def setUp(self):
        self.user = UserProfile.objects.filter()[0]
        amo.set_user(self.user)
        self.app = Addon.objects.get()
        self.app.premium_type = amo.ADDON_PREMIUM
        self.price = Price.objects.filter()[0]

        AddonPremium.objects.create(addon=self.app, price=self.price)
        self.seller = Mock(resource_uri='sellerres', user=self.user)
        self.account = Mock(user=self.user, name='paname', uri='acuri',
                            inactive=False, seller_uri='selluri')

    @patch('uuid.uuid4', Mock(return_value='lol'))
    @patch('mkt.developers.models.generate_key', Mock(return_value='poop'))
    @patch('mkt.developers.models.client')
    @fudge.with_fakes
    def test_create(self, client):
        client.upsert = (
            fudge.Fake()
                .expects_call()
                .with_args(method='product',
                           params={'seller': 'selluri', 'secret': 'poop',
                                   'external_id': self.app.pk},
                           lookup_by=['external_id'])
                .returns({'resource_uri': 'gpuri'})
                .next_call()
                .with_args(method='product_bango',
                           params={'seller_bango': 'acuri',
                                   'seller_product': 'gpuri',
                                   'name': self.app.name, 'categoryId': 1,
                                   'secret': 'poop'},
                           lookup_by=['seller_product'])
                .returns({'resource_uri': 'bpruri', 'bango_id': 'bango#',
                          'seller': 'selluri'}))

        apa = AddonPaymentAccount.create(
            'bango', addon=self.app, payment_account=self.account)
        eq_(apa.addon, self.app)
        eq_(apa.provider, 'bango')
        eq_(apa.set_price, self.price.price)
        eq_(apa.account_uri, 'acuri')
        eq_(apa.product_uri, 'bpruri')

        client.post_make_premium.assert_called_with(
            data={'bango': 'bango#', 'price': float(self.price.price),
                  'currencyIso': 'USD', 'seller_product_bango': 'bpruri'})
        client.post_update_rating.assert_called_with(
            data={'bango': 'bango#', 'rating': 'UNIVERSAL',
                  'ratingScheme': 'GLOBAL', 'seller_product_bango': 'bpruri'})

    @patch('mkt.developers.models.client')
    def test_update_price(self, client):
        new_price = 123456
        client.get_product_bango.return_value = {'bango': 'bango#'}

        payment_account = PaymentAccount.objects.create(
            user=self.user, name='paname', uri='acuri')

        apa = AddonPaymentAccount.objects.create(
            addon=self.app, provider='bango', account_uri='acuri',
            product_uri='bpruri', set_price=12345)

        apa.update_price(new_price)
        eq_(apa.set_price, new_price)

        client.post_make_premium.assert_called_with(
            data={'bango': 'bango#', 'price': 123456,
                  'currencyIso': 'USD', 'seller_product_bango': 'bpruri'})
        client.post_update_rating.assert_called_with(
            data={'bango': 'bango#', 'rating': 'UNIVERSAL',
                  'ratingScheme': 'GLOBAL', 'seller_product_bango': 'bpruri'})
