from datetime import datetime, timedelta

from nose import SkipTest
from nose.tools import eq_, ok_
from mock import Mock, patch

from django.core.exceptions import ObjectDoesNotExist

import amo
import amo.tests
from addons.models import Addon
from market.models import AddonPremium, Price
from users.models import UserProfile

from devhub.models import ActivityLog
from mkt.developers.models import (AddonPaymentAccount, PaymentAccount,
                                   SolitudeSeller)
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
        solsel_patcher = patch('mkt.developers.models.SolitudeSeller.create')
        self.solsel = solsel_patcher.start()
        self.solsel.return_value = self.seller = (
            SolitudeSeller.objects.create(
                resource_uri='selleruri', user=self.user))
        self.solsel.patcher = solsel_patcher

        client_patcher = patch('mkt.developers.models.client')
        self.client = client_patcher.start()
        self.client.patcher = client_patcher

    def tearDown(self):
        self.solsel.patcher.stop()
        self.client.patcher.stop()

    def test_create_bango(self):
        # Return a seller object without hitting Bango.
        self.client.api.bango.package.post.return_value = {
            'resource_uri': 'zipzap',
            'package_id': 123,
        }

        res = PaymentAccount.create_bango(
            self.user, {'account_name': 'Test Account'})
        eq_(res.name, 'Test Account')
        eq_(res.user, self.user)
        eq_(res.seller_uri, 'selleruri')
        eq_(res.bango_package_id, 123)
        eq_(res.uri, 'zipzap')

        self.client.api.bango.package.post.assert_called_with(
            data={'paypalEmailAddress': 'nobody@example.com',
                  'seller': 'selleruri'})

        self.client.api.bango.bank.post.assert_called_with(
            data={'seller_bango': 'zipzap'})

    def test_cancel(self):
        res = PaymentAccount.objects.create(
            name='asdf', user=self.user, uri='foo',
            solitude_seller=self.seller)

        addon = Addon.objects.get()
        AddonPaymentAccount.objects.create(
            addon=addon, provider='bango', account_uri='foo',
            payment_account=res, product_uri='bpruri', set_price=12345)

        res.cancel()
        assert res.inactive
        assert not AddonPaymentAccount.objects.exists()

    def test_get_details(self):
        package = Mock()
        package.get.return_value = {'full': {'vendorName': 'a',
                                             'some_other_value': 'b'}}
        self.client.api.bango.package.return_value = package

        res = PaymentAccount.objects.create(
            name='asdf', user=self.user, uri='/foo/bar/123',
            solitude_seller=self.seller)

        deets = res.get_details()
        eq_(deets['account_name'], res.name)
        eq_(deets['vendorName'], 'a')
        assert 'some_other_value' not in deets

        self.client.api.bango.package.assert_called_with('123')
        package.get.assert_called_with(data={'full': True})

    def test_update_account_details(self):
        res = PaymentAccount.objects.create(
            name='asdf', user=self.user, uri='foo',
            solitude_seller=self.seller)

        res.update_account_details(
            account_name='new name',
            vendorName='new vendor name',
            something_other_value='not a package key')
        eq_(res.name, 'new name')

        self.client.call_uri.assert_called_with(
            uri=res.uri, method='patch',
            data={'vendorName': 'new vendor name'})


class TestAddonPaymentAccount(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999') + ['market/prices']

    def setUp(self):
        self.user = UserProfile.objects.filter()[0]
        amo.set_user(self.user)
        self.app = Addon.objects.get()
        self.app.premium_type = amo.ADDON_PREMIUM
        self.price = Price.objects.filter()[0]

        AddonPremium.objects.create(addon=self.app, price=self.price)
        self.seller = SolitudeSeller.objects.create(
            resource_uri='sellerres', user=self.user
        )
        self.account = PaymentAccount.objects.create(
            solitude_seller=self.seller,
            user=self.user, name='paname', uri='acuri',
            inactive=False, seller_uri='selluri',
            bango_package_id=123
        )

    @patch('uuid.uuid4', Mock(return_value='lol'))
    @patch('mkt.developers.models.generate_key', Mock(return_value='poop'))
    @patch('mkt.developers.models.client')
    def test_create(self, client):
        client.api.generic.product.get_object.return_value = {
            'resource_uri': 'gpuri'}

        client.api.bango.product.get_object.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 'bango#', 'seller': 'selluri'
        }

        apa = AddonPaymentAccount.create(
            'bango', addon=self.app, payment_account=self.account)
        eq_(apa.addon, self.app)
        eq_(apa.provider, 'bango')
        eq_(apa.set_price, self.price.price)
        eq_(apa.account_uri, 'acuri')
        eq_(apa.product_uri, 'bpruri')

        client.api.bango.premium.post.assert_called_with(
            data={'bango': 'bango#', 'price': float(self.price.price),
                  'currencyIso': 'USD', 'seller_product_bango': 'bpruri'})

        eq_(client.api.bango.rating.post.call_args_list[0][1]['data'],
            {'bango': 'bango#', 'rating': 'UNIVERSAL',
             'ratingScheme': 'GLOBAL', 'seller_product_bango': 'bpruri'})
        eq_(client.api.bango.rating.post.call_args_list[1][1]['data'],
            {'bango': 'bango#', 'rating': 'GENERAL',
             'ratingScheme': 'USA', 'seller_product_bango': 'bpruri'})

    @patch('mkt.developers.models.client')
    def test_create_new(self, client):
        client.api.bango.product.get_object.side_effect = ObjectDoesNotExist
        client.api.bango.product.post.return_value = {
                'resource_uri': '', 'bango_id': 1}
        AddonPaymentAccount.create(
            'bango', addon=self.app, payment_account=self.account)
        ok_('packageId' in
            client.api.bango.product.post.call_args[1]['data'])

    @patch('mkt.developers.models.client')
    def test_update_price(self, client):
        new_price = 123456
        client.api.bango.product.get_object.return_value = {'bango': 'bango#'}

        payment_account = PaymentAccount.objects.create(
            user=self.user, name='paname', uri='/path/to/object',
            solitude_seller=self.seller)

        apa = AddonPaymentAccount.objects.create(
            addon=self.app, provider='bango', account_uri='acuri',
            payment_account=payment_account,
            product_uri='bpruri', set_price=987654)

        apa.update_price(new_price)
        eq_(apa.set_price, new_price)

        client.api.bango.premium.post.assert_called_with(
            data={'bango': 'bango#', 'price': new_price,
                  'currencyIso': 'USD', 'seller_product_bango': 'bpruri'})
        client.api.bango.rating.post.assert_called_with(
            data={'bango': 'bango#', 'rating': 'GENERAL',
                  'ratingScheme': 'USA', 'seller_product_bango': 'bpruri'})

    @patch('mkt.developers.models.client')
    def test_update_price_free(self, client):
        raise SkipTest("Disabled until Solitude is ready.")

        client.get_product_bango.return_value = {'bango': 'bango#'}

        payment_account = PaymentAccount.objects.create(
            user=self.user, name='paname', uri='/path/to/object',
            solitude_seller=self.seller)

        apa = AddonPaymentAccount.objects.create(
            addon=self.app, provider='bango', account_uri='acuri',
            payment_account=payment_account,
            product_uri='bpruri', set_price=123)

        apa.update_price(0)
        eq_(apa.set_price, 0)

        client.post_make_free.assert_called_with(
            data={'bango': 'bango#', 'seller_product_bango': 'bpruri'})
        client.post_update_rating.assert_called_with(
            data={'bango': 'bango#', 'rating': 'GENERAL',
                  'ratingScheme': 'USA', 'seller_product_bango': 'bpruri'})
