# -*- coding: utf-8 -*-
from decimal import Decimal
import json

import fudge
from fudge.inspector import arg
import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo.tests
from addons.models import Addon
from amo.urlresolvers import reverse
from devhub.models import AppLog
from market.models import (AddonPremium, AddonPurchase, PreApprovalUser,
                           Price, PriceCurrency)
from mkt.developers.models import (AddonPaymentAccount, PaymentAccount,
                                   SolitudeSeller)
from mkt.webapps.models import Webapp
from paypal import get_preapproval_url, PaypalError, PaypalDataError
from stats.models import Contribution
from users.models import UserProfile
from zadmin.models import DownloadSource


class PurchaseTest(amo.tests.TestCase):
    fixtures = ['base/users', 'market/prices', 'webapps/337141-steamcube']

    def setUp(self):
        self.create_switch(name='marketplace')
        self.addon = Addon.objects.get(pk=337141)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.price = Price.objects.get(pk=1)
        AddonPremium.objects.create(addon=self.addon, price=self.price,
                                    currencies=['BRL'])
        self.purchase_url = self.addon.get_purchase_url()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.brl = PriceCurrency.objects.create(currency='BRL',
                                                price=Decimal('0.5'),
                                                tier_id=1)

    def setup_package(self):
        self.seller = SolitudeSeller.objects.create(resource_uri='/path/to/sel',
                                                    uuid='seller-id',
                                                    user=self.user)
        self.account = PaymentAccount.objects.create(
            user=self.user, uri='asdf', name='test', inactive=False,
            solitude_seller=self.seller, bango_package_id=123)
        AddonPaymentAccount.objects.create(
            addon=self.addon, provider='bango', account_uri='foo',
            payment_account=self.account, product_uri='bpruri',
            set_price=12345)


class TestPurchaseEmbedded(PurchaseTest):

    def test_premium_only(self):
        self.addon.update(premium_type=amo.ADDON_FREE)
        eq_(self.client.post(self.purchase_url).status_code, 403)

    def test_get(self):
        eq_(self.client.get(self.purchase_url).status_code, 405)

    @mock.patch('paypal.get_paykey')
    def test_redirect(self, get_paykey):
        get_paykey.return_value = ['some-pay-key', '']
        res = self.client.post(self.purchase_url)
        assert 'some-pay-key' in res['Location']

    @mock.patch('paypal.get_paykey')
    def test_ajax(self, get_paykey):
        get_paykey.return_value = ['some-pay-key', '']
        res = self.client.post_ajax(self.purchase_url)
        eq_(json.loads(res.content)['paykey'], 'some-pay-key')

    @mock.patch('mkt.purchase.views.client.pay')
    @mock.patch('mkt.purchase.views.client.create_seller_for_pay')
    def test_ajax_solitude(self, create_seller_for_pay, pay):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)

        pay.return_value = {'pay_key': 'some-pay-key', 'uuid': 123,
                            'status': 'CREATED'}
        res = self.client.post_ajax(self.purchase_url)
        eq_(json.loads(res.content)['paykey'], 'some-pay-key')

    @fudge.patch('paypal.get_paykey')
    def test_paykey_amount(self, get_paykey):
        def check(*args, **kw):
            return args[0]['amount'] == Decimal('0.99')
        (get_paykey.expects_call()
                   .with_args(arg.passes_test(check))
                   .returns(('some-pay-key', '')))
        self.client.post_ajax(self.purchase_url)

    @fudge.patch('paypal.get_paykey')
    def test_paykey_currency(self, get_paykey):
        waffle.models.Switch.objects.create(name='currencies', active=True)

        def check(*args, **kw):
            return (args[0]['currency'] == 'BRL' and
                    args[0]['amount'] == Decimal('0.50'))
        (get_paykey.expects_call()
                   .with_args(arg.passes_test(check))
                   .returns(('some-pay-key', '')))
        self.client.post_ajax(self.purchase_url, data={'currency': 'BRL'})

    @fudge.patch('paypal.get_paykey')
    def test_paykey_invalid_currency(self, get_paykey):
        waffle.models.Switch.objects.create(name='currencies', active=True)

        def check(*args, **kw):
            return (args[0]['currency'] == 'USD' and
                    args[0]['amount'] == Decimal('0.99'))
        (get_paykey.expects_call()
                   .with_args(arg.passes_test(check))
                   .returns(('some-pay-key', '')))
        self.client.post_ajax(self.purchase_url, data={'tier': 0})

    @fudge.patch('paypal.get_paykey')
    def test_paykey_default_currency(self, get_paykey):
        PreApprovalUser.objects.create(user=self.user, currency='BRL',
                                       paypal_key='foo')

        def check(*args, **kw):
            return (args[0]['currency'] == 'BRL' and
                    args[0]['amount'] == Decimal('0.99'))
        (get_paykey.expects_call()
                   .with_args(arg.passes_test(check))
                   .returns(('some-pay-key', '')))
        self.client.post_ajax(self.purchase_url, data={'tier': 0})

    @fudge.patch('paypal.get_paykey')
    def test_paykey_error(self, get_paykey):
        get_paykey.expects_call().raises(PaypalError())
        res = self.client.post_ajax(self.purchase_url)
        assert json.loads(res.content)['error'].startswith('There was an')

    @fudge.patch('paypal.get_paykey')
    def test_paykey_unicode_error(self, get_paykey):
        get_paykey.expects_call().raises(PaypalDataError(u'Азәрбајҹан'))
        res = self.client.post_ajax(self.purchase_url)
        assert json.loads(res.content)['error'].startswith(u'Азәрбајҹан')

    @fudge.patch('paypal.get_paykey')
    def test_paykey_unicode_default(self, get_paykey):
        pde = PaypalDataError()
        pde.default = u'\xe9'
        get_paykey.expects_call().raises(pde)
        res = self.client.post_ajax(self.purchase_url)
        eq_(json.loads(res.content)['error'], u'\xe9')

    @mock.patch('paypal.get_paykey')
    def test_paykey_contribution(self, get_paykey):
        get_paykey.return_value = ['some-pay-key', '']
        self.client.post_ajax(self.purchase_url)
        cons = Contribution.objects.filter(type=amo.CONTRIB_PENDING)
        eq_(cons.count(), 1)
        eq_(cons[0].amount, Decimal('0.99'))

    def check_contribution(self, state):
        cons = Contribution.objects.all()
        eq_(cons.count(), 1)
        eq_(cons[0].type, state)

    @mock.patch('paypal.check_purchase')
    @mock.patch('paypal.get_paykey')
    def post_with_preapproval(self, get_paykey, check_purchase,
                              check_purchase_result=None, data=None):
        get_paykey.return_value = ['some-pay-key', 'COMPLETED']
        check_purchase.return_value = check_purchase_result
        return self.client.post_ajax(self.purchase_url, data=data or {})

    def test_paykey_pre_approval(self):
        res = self.post_with_preapproval(check_purchase_result='COMPLETED')
        eq_(json.loads(res.content)['status'], 'COMPLETED')
        self.check_contribution(amo.CONTRIB_PURCHASE)

    def test_contrib_tier_usd(self):
        # Test with currency switch in USD.
        self.post_with_preapproval(data={'currency': 'USD', 'tier': 1})
        cons = Contribution.objects.all()
        eq_(cons.count(), 1)
        eq_(cons[0].price_tier.id, 1)

    def test_contrib_tier_non_usd(self):
        # Test with currency switch in BRL.
        self.post_with_preapproval(data={'currency': 'BRL', 'tier': 1})
        cons = Contribution.objects.all()
        eq_(cons.count(), 1)
        eq_(cons[0].price_tier.id, 1)

    @mock.patch('mkt.purchase.views.client.pay')
    @mock.patch('mkt.purchase.views.client.create_seller_for_pay')
    @mock.patch('mkt.purchase.views.client.post_pay_check')
    def test_paykey_pre_approval_solitude(self, post_pay_check,
                                          create_seller_for_pay, pay):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)

        post_pay_check.return_value = {'status': 'COMPLETED'}
        pay.return_value = {'status': 'COMPLETED', 'uuid': 1, 'pay_key': '1'}
        res = self.client.post_ajax(self.purchase_url)
        eq_(json.loads(res.content)['status'], 'COMPLETED')
        self.check_contribution(amo.CONTRIB_PURCHASE)

    def test_paykey_pre_approval_disagree(self):
        res = self.post_with_preapproval(check_purchase_result='No!!!')
        eq_(json.loads(res.content)['status'], 'NOT-COMPLETED')
        self.check_contribution(amo.CONTRIB_PENDING)

    @mock.patch('paypal.check_purchase')
    @mock.patch('paypal.get_paykey')
    def test_paykey_pre_approval_no_ajax(self, get_paykey, check_purchase):
        get_paykey.return_value = ['some-pay-key', 'COMPLETED']
        check_purchase.return_value = 'COMPLETED'
        res = self.client.post(self.purchase_url)
        self.assertRedirects(res, self.addon.get_detail_url())

    @mock.patch('paypal.check_purchase')
    @mock.patch('paypal.get_paykey')
    def test_paykey_pre_approval_used(self, get_paykey, check_purchase):
        # TODO(solitude): remove this test, it will be redundant.
        check_purchase.return_value = 'COMPLETED'
        get_paykey.return_value = 'some-pay-key', 'COMPLETED'
        pre = PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        self.client.post_ajax(self.purchase_url)
        eq_(get_paykey.call_args[0][0]['preapproval'], pre)

    @mock.patch('paypal.check_purchase')
    @mock.patch('paypal.get_paykey')
    def test_paykey_pre_approval_empty(self, get_paykey, check_purchase):
        # TODO(solitude): remove this test, it will be invalid once solitude
        # is live. I think it's trying to test that things still work if
        # pre approval is empty.
        check_purchase.return_value = 'CREATED'
        get_paykey.return_value = '...', 'CREATED'
        PreApprovalUser.objects.create(user=self.user, paypal_key='')
        res = self.client.post_ajax(self.purchase_url)
        eq_(res.status_code, 200)

    @mock.patch('addons.models.Addon.has_purchased')
    def test_has_purchased(self, has_purchased):
        has_purchased.return_value = True
        res = self.client.post(self.purchase_url)
        eq_(res.status_code, 403)

    def test_zero(self):
        self.price.update(price=Decimal('0.00'))
        res = self.client.post_ajax(self.purchase_url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'COMPLETED')
        eq_(Contribution.objects.all().count(), 0)
        eq_(AddonPurchase.objects.filter(addon=self.addon).count(), 1)

    def make_contribution(self, type=amo.CONTRIB_PENDING):
        return Contribution.objects.create(type=type,
            uuid='123', addon=self.addon, paykey='1234', user=self.user)

    @fudge.patch('paypal.get_paykey')
    def test_split(self, get_paykey):
        def check_call(*args, **kw):
            assert 'chains' not in kw
        (get_paykey.expects_call()
                   .calls(check_call)
                   .returns(('payKey', 'paymentExecStatus')))
        self.client.post(self.addon.get_purchase_url(),
                         {'result_type': 'json'})

    @mock.patch('paypal.get_paykey')
    def test_contribution_client_data(self, get_paykey):
        get_paykey.return_value = ['some-pay-key', '']
        download_source = DownloadSource.objects.create(name='mkt-home')
        device_type = 'desktop'
        user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:16.0)'

        self.client.post_ajax(self.purchase_url,
                              data={'src': download_source.name,
                                    'device_type': device_type,
                                    'is_chromeless': False},
                              **{'HTTP_USER_AGENT': user_agent})
        cons = Contribution.objects.filter(type=amo.CONTRIB_PENDING)
        eq_(cons.count(), 1)
        eq_(cons[0].client_data.download_source, download_source)
        eq_(cons[0].client_data.device_type, device_type)
        eq_(cons[0].client_data.user_agent, user_agent)
        eq_(cons[0].client_data.is_chromeless, False)
        eq_(not cons[0].client_data.language, False)
        eq_(not cons[0].client_data.region, False)


class TestPurchaseDetails(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)
        self.make_premium(self.webapp)
        self.url = self.webapp.get_detail_url()
        self.pre_url = reverse('detail.purchase.preapproval',
                               args=[self.webapp.app_slug])

    @mock.patch('users.models.UserProfile.has_preapproval_key')
    def test_details_no_preauth(self, has_preapproval_key):
        raise SkipTest

        self.client.login(username='regular@mozilla.com', password='password')
        has_preapproval_key.return_value = False
        res = self.client.get(self.url)
        form = pq(res.content)('#pay form')
        eq_(len(form), 1)
        eq_(form.eq(0).attr('action'), '{preapprovalUrl}')

    @mock.patch('users.models.UserProfile.has_preapproval_key')
    def test_details_preauth(self, has_preapproval_key):
        self.client.login(username='regular@mozilla.com', password='password')
        has_preapproval_key.return_value = True
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('#pay form')), 0)

    def test_pre_approval_not_logged_in(self):
        res = self.client.post(self.pre_url)
        eq_(res.status_code, 302)

    @mock.patch('paypal.get_preapproval_key')
    def test_pre_approval(self, get_preapproval_key):
        get_preapproval_key.return_value = {'preapprovalKey': 'x'}
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.post(self.pre_url, {'currency': 'USD'})
        eq_(res.status_code, 302)
        eq_(res['Location'], get_preapproval_url('x'))
