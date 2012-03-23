# -*- coding: utf-8 -*-
from decimal import Decimal
import json

from django.conf import settings

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
from market.models import (AddonPremium, AddonPurchase, PreApprovalUser,
                           Price, PriceCurrency)
import paypal
from paypal import PaypalError, PaypalDataError
from stats.models import Contribution
from users.models import UserProfile


class TestPurchaseEmbedded(amo.tests.TestCase):
    fixtures = ['base/users', 'prices', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        waffle.models.Flag.objects.create(name='allow-pre-auth', everyone=True)
        self.addon = Addon.objects.get(pk=337141)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        AddonPremium.objects.create(addon=self.addon, price_id=1)
        self.purchase_url = self.addon.get_purchase_url()
        self.client.login(username='regular@mozilla.com', password='password')
        self.brl = PriceCurrency.objects.create(currency='BRL',
                                                price=Decimal('0.5'),
                                                tier_id=1)

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
        def check(*args, **kw):
            return (args[0]['currency'] == 'BRL' and
                    args[0]['amount'] == Decimal('0.50'))
        (get_paykey.expects_call()
                   .with_args(arg.passes_test(check))
                   .returns(('some-pay-key', '')))
        self.client.post_ajax(self.purchase_url, data={'currency': 'BRL'})

    @fudge.patch('paypal.get_paykey')
    def test_paykey_invalid_currency(self, get_paykey):
        def check(*args, **kw):
            return (args[0]['currency'] == 'USD' and
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
                             check_purchase_result=None):
        get_paykey.return_value = ['some-pay-key', 'COMPLETED']
        check_purchase.return_value = check_purchase_result
        return self.client.post_ajax(self.purchase_url)

    def test_paykey_pre_approval(self):
        res = self.post_with_preapproval(check_purchase_result='COMPLETED')
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
    @fudge.patch('paypal.get_paykey')
    # Turning on the allow-pre-auth flag.
    @mock.patch.object(waffle, 'flag_is_active', lambda x, y: True)
    def test_paykey_pre_approval_used(self, get_paykey, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        pre = PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        (get_paykey.expects_call()
                   .with_matching_args(preapproval=pre)
                   .returns(('some-pay-key', 'COMPLETED')))
        self.client.post_ajax(self.purchase_url)

    @mock.patch('paypal.check_purchase')
    @fudge.patch('paypal._call')
    # Turning on the allow-pre-auth flag.
    @mock.patch.object(waffle, 'flag_is_active', lambda x, y: True)
    def test_paykey_pre_approval_empty(self, _call, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        PreApprovalUser.objects.create(user=self.user, paypal_key='')
        r = lambda s: 'receiverList.receiver(0).email' in s
        (_call.expects_call()
              .with_matching_args(arg.any(), arg.passes_test(r))
              .returns({'payKey': 'some-pay-key',
                        'paymentExecStatus': 'COMPLETED'}))
        self.client.post_ajax(self.purchase_url)

    @mock.patch('addons.models.Addon.has_purchased')
    def test_has_purchased(self, has_purchased):
        has_purchased.return_value = True
        res = self.client.post(self.purchase_url)
        eq_(res.status_code, 403)

    @mock.patch('addons.models.Addon.has_purchased')
    def test_not_has_purchased(self, has_purchased):
        has_purchased.return_value = False
        res = self.client.post_ajax(self.purchase_url)
        eq_(res.status_code, 200)

    def make_contribution(self, type=amo.CONTRIB_PENDING):
        return Contribution.objects.create(type=type,
            uuid='123', addon=self.addon, paykey='1234', user=self.user)

    def get_url(self, status):
        return self.addon.get_purchase_url('done', [status])

    @mock.patch('paypal.check_purchase')
    def test_check_purchase(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        self.client.get_ajax('%s?uuid=%s' % (self.get_url('complete'), '123'))
        cons = Contribution.objects.all()
        eq_(cons.count(), 1)
        eq_(cons[0].type, amo.CONTRIB_PURCHASE)
        assert cons[0].uuid

    @mock.patch('paypal.check_purchase')
    def test_check_addon_purchase_error(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.return_value = 'ERROR'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))

        doc = pq(res.content)
        eq_(doc('#paypal-error').length, 1)
        eq_(res.context['status'], 'error')

    @mock.patch('paypal.check_purchase')
    def test_check_addon_purchase(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))
        eq_(AddonPurchase.objects.filter(addon=self.addon).count(), 1)
        eq_(res.context['status'], 'complete')
        # Test that we redirect to app detail page.

    def test_check_cancel(self):
        # Fix when we implement payment confirmation.
        raise SkipTest

        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('cancel'), '123'))
        eq_(Contribution.objects.filter(type=amo.CONTRIB_PURCHASE).count(), 0)
        eq_(res.context['status'], 'cancel')

    @mock.patch('paypal.check_purchase')
    def test_check_wrong_uuid(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), 'foo'))
        eq_(res.status_code, 404)

    @mock.patch('paypal.check_purchase')
    def test_check_pending(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.return_value = 'PENDING'
        self.make_contribution()
        self.client.get_ajax('%s?uuid=%s' % (self.get_url('complete'), '123'))
        eq_(Contribution.objects.filter(type=amo.CONTRIB_PURCHASE).count(), 0)

    @mock.patch('paypal.check_purchase')
    def test_check_pending_error(self, check_purchase):
        # Fix when we implement payment confirmation.
        raise SkipTest

        check_purchase.side_effect = Exception('wtf')
        self.make_contribution()
        url = '%s?uuid=%s' % (self.get_url('complete'), '123')
        res = self.client.get_ajax(url)
        eq_(res.context['result'], 'ERROR')

    def test_check_thankyou(self):
        # Fix when we implement payment confirmation.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        eq_(self.client.get(url).status_code, 403)
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        eq_(self.client.get(url).status_code, 200)

    @mock.patch('users.models.UserProfile.has_preapproval_key')
    def test_prompt_preapproval(self, has_preapproval_key):
        # Fix when we implement pre-auth.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        has_preapproval_key.return_value = False
        res = self.client.get(url)
        eq_(pq(res.content)('#preapproval').attr('action'),
            reverse('users.payments.preapproval'))

    @mock.patch('users.models.UserProfile.has_preapproval_key')
    def test_already_preapproved(self, has_preapproval_key):
        # Fix when we implement pre-auth.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        has_preapproval_key.return_value = True
        res = self.client.get(url)
        eq_(pq(res.content)('#preapproval').length, 0)

    def test_trigger(self):
        # Fix when we implement confirmation/receipt.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        dest = reverse('downloads.watermarked', args=[self.file.pk])
        res = self.client.get('%s?realurl=%s' % (url, dest))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('a.trigger_download').attr('href'), dest)

    def test_trigger_nasty(self):
        # Fix when we implement confirmation/receipt.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        res = self.client.get('%s?realurl=%s' % (url, 'http://bad.site/foo'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('a.trigger_download').attr('href'), '/foo')

    @mock.patch('paypal.check_purchase')
    def test_result_page(self, check_purchase):
        # Fix when we implement confirmation.
        raise SkipTest

        check_purchase.return_value = 'COMPLETED'
        Contribution.objects.create(addon=self.addon, uuid='1',
                                    user=self.user, paykey='sdf',
                                    type=amo.CONTRIB_PENDING)
        url = self.addon.get_purchase_url('done', ['complete'])
        doc = pq(self.client.get('%s?uuid=1' % url).content)
        eq_(doc('#paypal-thanks').length, 1)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    def test_trigger_webapp(self):
        # Fix when we implement confirmation/receipt.
        raise SkipTest

        url = self.addon.get_purchase_url('thanks')
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        doc = pq(self.client.get(url).content)
        eq_(doc('.trigger_app_install').attr('data-manifest-url'),
            self.addon.manifest_url)

    @fudge.patch('paypal.get_paykey')
    def test_split(self, get_paykey):
        def check_call(*args, **kw):
            assert 'chains' not in kw
        (get_paykey.expects_call()
                   .calls(check_call)
                   .returns(('payKey', 'paymentExecStatus')))
        self.client.post(self.addon.get_purchase_url(),
                         {'result_type': 'json'})
