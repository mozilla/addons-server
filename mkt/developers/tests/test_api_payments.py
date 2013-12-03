import json

from django.core.urlresolvers import reverse

from curling.lib import HttpClientError, HttpServerError
from mock import Mock, patch
from nose.tools import eq_, ok_

import amo
from addons.models import AddonUpsell, AddonUser
from amo.tests import app_factory, TestCase
from market.models import AddonPremium, Price

from mkt.api.tests.test_oauth import RestOAuth
from mkt.developers.api_payments import AddonPaymentAccountSerializer
from mkt.developers.models import (AddonPaymentAccount, PaymentAccount,
                                   SolitudeSeller)
from mkt.developers.tests.test_providers import Patcher
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


package_data = {
    'companyName': 'company',
    'vendorName': 'vendor',
    'financeEmailAddress': 'a@a.com',
    'adminEmailAddress': 'a@a.com',
    'supportEmailAddress': 'a@a.com',
    'address1': 'address 1',
    'addressCity': 'city',
    'addressState': 'state',
    'addressZipCode': 'zip',
    'addressPhone': '123',
    'countryIso': 'BRA',
    'currencyIso': 'EUR',
    'account_name': 'new'
}

bank_data = {
    'bankAccountPayeeName': 'name',
    'bankAccountNumber': '123',
    'bankAccountCode': '123',
    'bankName': 'asd',
    'bankAddress1': 'address 2',
    'bankAddressZipCode': '123',
    'bankAddressIso': 'BRA',
}

payment_data = package_data.copy()
payment_data.update(bank_data)


class UpsellCase(TestCase):

    def url(self, app):
        return reverse('app-detail', kwargs={'pk': app.pk})

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


class AccountCase(Patcher, TestCase):
    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        self.seller = SolitudeSeller.objects.create(user_id=2519)
        self.account = PaymentAccount.objects.create(user_id=2519,
            solitude_seller=self.seller, account_id=123, name='mine')
        self.app_payment_list = reverse('app-payment-account-list')
        self.payment_list = reverse('payment-account-list')
        self.payment_url = reverse('payment-account-detail',
                                   kwargs={'pk': self.account.pk})

        super(AccountCase, self).setUp()

        self.patched_client.api.generic.product.get_object.return_value = {
            'resource_uri': 'foo'}
        self.patched_client.api.bango.product.get_object.return_value = {
            'resource_uri': 'foo', 'bango_id': 'bar'}

    def create(self):
        self.payment = AddonPaymentAccount.objects.create(addon=self.app,
            payment_account=self.account)
        self.app_payment_detail = reverse('app-payment-account-detail',
                                          kwargs={'pk': self.payment.pk})

    def create_price(self):
        price = Price.objects.create(price='1')
        AddonPremium.objects.create(addon=self.app, price=price)

    def create_user(self):
        AddonUser.objects.create(addon=self.app, user=self.profile)

    def other(self, shared=False):
        self.seller2 = SolitudeSeller.objects.create(user_id=31337, uuid='foo')
        self.other_account = PaymentAccount.objects.create(user_id=31337,
            solitude_seller=self.seller2, account_id=123,
            seller_uri='seller_uri', uri='uri', shared=shared, name='other')
        self.other_url = reverse('payment-account-detail',
                                   kwargs={'pk': self.other_account.pk})
        return self.data(overrides={'payment_account': self.other_url})

    def data(self, overrides=None):
        res = {
            'addon': self.app.get_api_url(pk=True),
            'payment_account': self.payment_url,
            'provider': 'bango',
        }
        if overrides:
            res.update(overrides)
        return res


class TestSerializer(AccountCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def test_serialize(self):
        # Just a smoke test that we can serialize this correctly.
        self.create()
        res = AddonPaymentAccountSerializer(self.payment).data
        eq_(res['url'], self.app_payment_detail)

    def test_free(self):
        # Just a smoke test that we can serialize this correctly.
        self.create()
        self.app.update(premium_type=amo.ADDON_FREE)
        res = AddonPaymentAccountSerializer(self.payment)
        ok_(not res.is_valid())


class TestPaymentAccount(AccountCase, RestOAuth):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def test_anonymous(self):
        r = self.anon.get(self.payment_url)
        eq_(r.status_code, 403)

        r = self.anon.get(self.payment_list)
        eq_(r.status_code, 403)

    def test_get_payments_account_list(self):
        self.other()
        res = self.client.get(self.payment_list)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['account_name'], 'mine')
        eq_(data['objects'][0]['resource_uri'], self.payment_url)

    def test_get_payments_account(self):
        res = self.client.get(self.payment_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['account_name'], 'mine')
        eq_(data['resource_uri'], self.payment_url)

    def test_get_other_payments_account(self):
        self.other()
        res = self.client.get(self.other_url)
        eq_(res.status_code, 404, res.content)

    def test_create(self):
        res = self.client.post(self.payment_list,
                               data=json.dumps(payment_data))
        data = json.loads(res.content)
        eq_(data['account_name'], 'new')
        new_account = PaymentAccount.objects.get(name='new')
        ok_(new_account.pk != self.account.pk)
        eq_(new_account.user, self.user.get_profile())
        data = self.bango_patcher.package.post.call_args[1]['data']
        expected = package_data.copy()
        expected.pop('account_name')
        for key in expected.keys():
            eq_(package_data[key], data[key])

    def test_update_payments_account(self):
        res = self.client.put(self.payment_url,
                              data=json.dumps(payment_data))
        eq_(res.status_code, 204, res.content)
        self.account.reload()
        eq_(self.account.name, 'new')
        data = self.bango_patcher.api.by_url().patch.call_args[1]['data']
        expected = package_data.copy()
        expected.pop('account_name')
        for key in expected.keys():
            eq_(package_data[key], data[key])

    def test_update_other_payments_account(self):
        self.other()
        res = self.client.put(self.other_url,
                              data=json.dumps(payment_data))
        eq_(res.status_code, 404, res.content)
        self.other_account.reload()
        eq_(self.other_account.name, 'other')  # not "new".

    def test_delete_payments_account(self):
        self.create_user()
        self.create()
        eq_(self.account.inactive, False)
        res = self.client.delete(self.payment_url)
        eq_(res.status_code, 204, res.content)
        self.account.reload()
        eq_(self.account.inactive, True)

    def test_delete_shared(self):
        self.create_user()
        self.create()
        self.account.update(shared=True)
        eq_(self.account.inactive, False)
        res = self.client.delete(self.payment_url)
        eq_(res.status_code, 409)

    def test_delete_others_payments_account(self):
        self.create_user()
        self.create()
        self.other()
        eq_(self.other_account.inactive, False)
        res = self.client.delete(self.other_url)
        eq_(res.status_code, 404, res.content)
        self.other_account.reload()
        eq_(self.other_account.inactive, False)

    def test_create_fail(self):
        err = {'broken': True}
        self.bango_patcher.package.post.side_effect = HttpClientError(
            content=err)
        res = self.client.post(self.payment_list,
                               data=json.dumps(payment_data))
        eq_(res.status_code, 500)
        eq_(json.loads(res.content), err)

    def test_create_fail2(self):
        self.bango_patcher.package.post.side_effect = HttpServerError()
        res = self.client.post(self.payment_list,
                               data=json.dumps(payment_data))
        eq_(res.status_code, 500)


class TestAddonPaymentAccount(AccountCase, RestOAuth):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def test_empty(self):
        eq_(self.client.post(self.app_payment_list, data={}).status_code, 400)

    def test_not_allowed(self):
        res = self.client.post(self.app_payment_list,
                               data=json.dumps(self.data()))
        eq_(res.status_code, 403)

    def test_allowed(self):
        self.create_price()
        self.create_user()
        res = self.client.post(self.app_payment_list,
                               data=json.dumps(self.data()))
        eq_(res.status_code, 201, res.content)

        account = AddonPaymentAccount.objects.get()
        eq_(account.payment_account, self.account)

    def test_cant_change_addon(self):
        app = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=app, user=self.profile)
        self.create()
        self.create_price()
        self.create_user()

        data = self.data({'payment_account': self.payment_url,
                          'addon': app.get_api_url(pk=True)})
        res = self.client.patch(self.app_payment_detail, data=json.dumps(data))
        # Ideally we should make this a 400.
        eq_(res.status_code, 403, res.content)

    def test_cant_use_someone_elses(self):
        data = self.other(shared=False)
        self.create_price()
        self.create_user()
        res = self.client.post(self.app_payment_list, data=json.dumps(data))
        eq_(res.status_code, 403, res.content)

    def test_can_shared(self):
        data = self.other(shared=True)
        self.create_price()
        self.create_user()
        res = self.client.post(self.app_payment_list, data=json.dumps(data))
        eq_(res.status_code, 201, res.content)


class TestPaymentStatus(AccountCase, RestOAuth):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def setUp(self):
        super(TestPaymentStatus, self).setUp()
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


class TestPaymentDebug(AccountCase, RestOAuth):
    fixtures = fixture('webapp_337141', 'user_999', 'user_2519')

    def setUp(self):
        super(TestPaymentDebug, self).setUp()
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
