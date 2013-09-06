import json

from django.core.urlresolvers import reverse
from mock import Mock, patch
from nose.tools import eq_, ok_

import amo
from addons.models import AddonUpsell, AddonUser
from amo.tests import app_factory, TestCase
from market.models import AddonPremium, Price

from mkt.api.base import get_url
from mkt.api.tests.test_oauth import get_absolute_url, RestOAuth
from mkt.developers.api_payments import PaymentAccountSerializer
from mkt.developers.models import (AddonPaymentAccount, PaymentAccount,
                                   SolitudeSeller)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class UpsellCase(TestCase):

    def url(self, app):
        return get_absolute_url(get_url('app', pk=app.pk), absolute=False)

    def setUp(self):
        self.free = Webapp.objects.get(pk=337141)
        self.free_url = self.url(self.free)
        self.premium = app_factory(premium_type=amo.ADDON_PREMIUM)
        self.premium_url = self.url(self.premium)
        self.upsell_list = reverse('app-upsell-list')

    def create_upsell(self):
        self.upsell = AddonUpsell.objects.create(free=self.free,
                                                 premium=self.premium)
        self.upsell_url = reverse('app-upsell-detail',
                                  kwargs={'pk': self.upsell.pk})

    def create_allowed(self):
        AddonUser.objects.create(addon=self.free, user=self.profile)
        AddonUser.objects.create(addon=self.premium, user=self.profile)


class TestUpsell(RestOAuth, UpsellCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestUpsell, self).setUp()
        UpsellCase.setUp(self)
        self.create_switch('allow-b2g-paid-submission')

    def test_create(self):
        eq_(self.client.post(self.upsell_list, data={}).status_code, 400)

    def test_missing(self):
        res = self.client.post(self.upsell_list,
                               data=json.dumps({'free': self.free_url}))
        eq_(res.status_code, 400)
        eq_(res.json['premium'], [u'This field is required.'])

    def test_not_allowed(self):
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.free_url, 'premium': self.premium_url}))
        eq_(res.status_code, 403)

    def test_allowed(self):
        self.create_allowed()
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.free_url, 'premium': self.premium_url}))
        eq_(res.status_code, 201)

    def test_delete_not_allowed(self):
        self.create_upsell()
        eq_(self.client.delete(self.upsell_url).status_code, 403)

    def test_delete_allowed(self):
        self.create_upsell()
        self.create_allowed()
        eq_(self.client.delete(self.upsell_url).status_code, 204)

    def test_wrong_way_around(self):
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.premium_url, 'premium': self.free_url}))
        eq_(res.status_code, 400)

    def test_patch_new_not_allowed(self):
        # Trying to patch to a new object you do not have access to.
        self.create_upsell()
        self.create_allowed()
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 403)

    def test_patch_old_not_allowed(self):
        # Trying to patch an old object you do not have access to.
        self.create_upsell()
        AddonUser.objects.create(addon=self.free, user=self.profile)
        # We did not give you access to patch away from self.premium.
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=another, user=self.profile)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 403)

    def test_patch(self):
        self.create_upsell()
        self.create_allowed()
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=another, user=self.profile)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 200)


class TestPayment(RestOAuth, UpsellCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestPayment, self).setUp()
        UpsellCase.setUp(self)
        self.payment_url = reverse('app-payments-detail',
                                   kwargs={'pk': 337141})

    def test_get_not_allowed(self):
        res = self.client.get(self.payment_url)
        eq_(res.status_code, 403)

    def test_get_allowed(self):
        AddonUser.objects.create(addon_id=337141, user=self.profile)
        res = self.client.get(self.payment_url)
        eq_(res.json['upsell'], None)
        eq_(res.status_code, 200)

    def test_upsell(self):
        AddonUser.objects.create(addon_id=337141, user=self.profile)
        upsell = AddonUpsell.objects.create(free_id=337141,
                                            premium=self.premium)
        res = self.client.get(self.payment_url)
        eq_(res.json['upsell'],
            reverse('app-upsell-detail', kwargs={'pk': upsell.pk}))
        eq_(res.status_code, 200)


class AccountCase(TestCase):

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        self.seller = SolitudeSeller.objects.create(user_id=999)
        self.account = PaymentAccount.objects.create(user_id=999,
            solitude_seller=self.seller, bango_package_id=123)
        self.payment_list = reverse('app-payment-account-list')

    def create(self):
        self.payment = AddonPaymentAccount.objects.create(addon=self.app,
            payment_account=self.account)
        self.payment_detail = reverse('app-payment-account-detail',
                                      kwargs={'pk': self.payment.pk})

    def create_price(self):
        price = Price.objects.create(price='1')
        AddonPremium.objects.create(addon=self.app, price=price)

    def create_user(self):
        AddonUser.objects.create(addon=self.app, user=self.profile)


class TestSerializer(AccountCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def test_serialize(self):
        # Just a smoke test that we can serialize this correctly.
        self.create()
        res = PaymentAccountSerializer(self.payment).data
        eq_(res['url'], self.payment_detail)

    def test_free(self):
        # Just a smoke test that we can serialize this correctly.
        self.create()
        self.app.update(premium_type=amo.ADDON_FREE)
        res = PaymentAccountSerializer(self.payment)
        ok_(not res.is_valid())


class TestPaymentAccount(RestOAuth, AccountCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def setUp(self):
        super(TestPaymentAccount, self).setUp()
        AccountCase.setUp(self)
        self.payment_url = get_absolute_url(
            get_url('account', pk=self.account.pk),
            api_name='payments', absolute=False)

    def data(self, overrides=None):
        res = {
            'addon': self.app.get_api_url(pk=True),
            'payment_account': self.payment_url,
            'provider': 'bango',
        }
        if overrides:
            res.update(overrides)
        return res

    def test_empty(self):
        eq_(self.client.post(self.payment_list, data={}).status_code, 400)

    def test_not_allowed(self):
        res = self.client.post(self.payment_list, data=json.dumps(self.data()))
        eq_(res.status_code, 403)

    @patch('mkt.developers.models.client')
    def test_allowed(self, client):
        client.api.generic.product.get_object.return_value = {
            'resource_uri': 'foo'}
        client.api.bango.product.get_object.return_value = {
            'resource_uri': 'foo', 'bango_id': 'bar'}

        self.create_price()
        self.create_user()
        res = self.client.post(self.payment_list, data=json.dumps(self.data()))
        eq_(res.status_code, 201, res.content)

        account = AddonPaymentAccount.objects.get()
        eq_(account.payment_account, self.account)

    @patch('mkt.developers.models.client')
    def test_cant_change_addon(self, client):
        client.api.generic.product.get_object.return_value = {
            'resource_uri': 'foo'}
        client.api.bango.product.get_object.return_value = {
            'resource_uri': 'foo', 'bango_id': 'bar'}

        app = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=app, user=self.profile)
        self.create()
        self.create_price()
        self.create_user()

        data = self.data({'payment_account': self.payment_url,
                          'addon': app.get_api_url(pk=True)})
        res = self.client.patch(self.payment_detail, data=json.dumps(data))
        # Ideally we should make this a 400.
        eq_(res.status_code, 403, res.content)


class TestPaymentStatus(RestOAuth, AccountCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def setUp(self):
        super(TestPaymentStatus, self).setUp()
        AccountCase.setUp(self)
        self.create()
        self.payment.account_uri = '/bango/package/1/'
        self.payment.save()
        self.list_url = reverse('app-payments-status-list',
                                kwargs={'pk': 337141})

    def test_no_auth(self):
        eq_(self.anon.post(self.list_url, data={}).status_code, 403)

    def test_not_owner(self):
        eq_(self.client.post(self.list_url, data={}).status_code, 403)

    def test_no_account(self):
        self.payment.account_uri = ''
        self.payment.save()
        eq_(self.client.post(self.list_url, data={}).status_code, 400)

    @patch('mkt.developers.api_payments.get_client')
    def test_owner(self, get_client):
        client = Mock()
        client.api.bango.status.post.return_value = {'status': 1}
        get_client.return_value = client
        AddonUser.objects.create(addon_id=337141, user_id=self.user.pk)
        res = self.client.post(self.list_url, data={})
        eq_(res.json['bango']['status'], 'passed')
        eq_(res.status_code, 200)


class TestPaymentDebug(RestOAuth, AccountCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def setUp(self):
        super(TestPaymentDebug, self).setUp()
        AccountCase.setUp(self)
        self.create()
        self.payment.account_uri = '/bango/package/1/'
        self.payment.save()
        self.list_url = reverse('app-payments-debug-list',
                                kwargs={'pk': 337141})

    def test_no_auth(self):
        eq_(self.anon.get(self.list_url).status_code, 403)

    def test_no_perms(self):
        eq_(self.client.get(self.list_url).status_code, 403)

    @patch('mkt.developers.api_payments.get_client')
    def test_good(self, get_client):
        client = Mock()
        client.api.bango.debug.get.return_value = {'bango':
                                                   {'environment': 'dev'}}
        get_client.return_value = client
        self.app.update(premium_type=amo.ADDON_FREE_INAPP)
        self.grant_permission(self.profile, 'Transaction:Debug')
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        eq_(res.json['bango']['environment'], 'dev')
