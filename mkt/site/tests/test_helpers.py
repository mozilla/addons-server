# -*- coding: utf-8 -*-
import json

from django.conf import settings

import fudge
import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import AddonCategory, Category
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from market.models import AddonPremium, AddonPurchase
from users.models import UserProfile

from mkt.site.helpers import (css, get_login_link, js, market_button,
                              market_tile)
from mkt.webapps.models import Webapp


class TestMarketButton(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        self.webapp = Webapp.objects.filter(pk=337141).no_transforms()[0]
        self.user = UserProfile.objects.get(pk=999)
        request = mock.Mock()
        request.amo_user = self.user
        request.groups = ()
        request.check_ownership.return_value = False
        request.GET = {'src': 'foo'}
        request.groups = ()
        request.GAIA = False
        request.MOBILE = True
        request.TABLET = False
        request.META = {'HTTP_USER_AGENT': 'Mozilla/5.0 (Mobile; rv:17.0) '
                                           'Gecko/17.0 Firefox/17.0'}
        self.context = {'request': request}

    def test_not_webapp(self):
        self.webapp.update(type=amo.ADDON_EXTENSION)
        # TODO: raise a more sensible error.
        self.assertRaises(UnboundLocalError, market_button,
                          self.context, self.webapp)

    def test_is_webapp(self):
        doc = pq(market_tile(self.context, self.webapp))
        eq_(doc('.price').text(), 'Free')

        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['manifest_url'], self.webapp.manifest_url)
        eq_(data['recordUrl'], urlparams(self.webapp.get_detail_url('record'),
                                         src='foo'))
        eq_(data['preapprovalUrl'], reverse('detail.purchase.preapproval',
                                            args=[self.webapp.app_slug]))
        eq_(data['id'], str(self.webapp.pk))
        eq_(data['name'], str(self.webapp.name))
        eq_(data['src'], 'foo')

    def test_is_premium_webapp(self):
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        eq_(doc('.price').text(), '$1.00')

        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['manifest_url'], self.webapp.manifest_url)
        eq_(data['price'], 1.0)
        eq_(data['priceLocale'], '$1.00')
        eq_(data['purchase'], self.webapp.get_purchase_url())
        eq_(data['isPurchased'], False)

        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').text(),
            'This app is available for purchase on only Firefox OS.')

    def test_is_premium_no_payment(self):
        self.make_premium(self.webapp, price='0.00')
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        assert 'price' not in data

    def test_is_premium_webapp_gaia(self):
        self.context['request'].GAIA = True
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        eq_(doc('.price').text(), '$1.00')

        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_is_premium_webapp_foreign(self):
        self.make_premium(self.webapp)
        with self.activate('fr'):
            doc = pq(market_tile(self.context, self.webapp))
            data = json.loads(doc('.mkt-tile').attr('data-product'))
            eq_(data['price'], 1.0)
            eq_(data['priceLocale'], u'1,00 €')

    def test_is_premium_purchased(self):
        AddonPurchase.objects.create(user=self.user, addon=self.webapp)
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['isPurchased'], True)

    def test_is_premium_disabled(self):
        self.make_premium(self.webapp)
        self.create_switch(name='disabled-payments')
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').text(),
            'This app is temporarily unavailable for purchase.')

    def test_is_desktop_enabled(self):
        self.webapp._device_types = [amo.DEVICE_DESKTOP]
        self.context['request'].MOBILE = False
        self.context['request'].META['HTTP_USER_AGENT'] = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.6; rv:18.0) Gecko/18.0 '
            'Firefox/18.0')
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Found %r class' % cls
        assert 'incompatible' not in cls, 'Found %r class' % cls
        eq_(doc('.bad-app').length, 0)

    def test_needs_firefox_for_android(self):
        self.context['request'].META['HTTP_USER_AGENT'] = (
            'Mozilla/5.0 (Linux; U; Android 2.3.3; en-au; GT-I9100 Build)')
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Could not find %r class' % cls
        assert 'incompatible' in cls, 'Could not find %r class' % cls
        eq_(doc('.bad-app').length, 0)

    def test_needs_firefox_for_android_upgrade(self):
        # Only Firefox for Android 17.0+ has support for `navigator.mozApps`.
        self.context['request'].META['HTTP_USER_AGENT'] = (
            'Mozilla/5.0 (Mobile; rv:16.0) Gecko/16.0 Firefox/16.0')
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Could not find %r class' % cls
        assert 'incompatible' in cls, 'Could not find %r class' % cls
        eq_(doc('.bad-app').length, 0)

    def test_is_premium_android_disabled(self):
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').text(),
            'This app is available for purchase on only Firefox OS.')

    def test_is_free_enabled_android(self):
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_is_free_enabled_gaia(self):
        self.context['request'].GAIA = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_can_install_mobile(self):
        self.webapp._device_types = [amo.DEVICE_MOBILE]
        self.context['request'].MOBILE = True
        self.context['request'].TABLET = False
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_cannot_install_mobile_only(self):
        self.webapp._device_types = [amo.DEVICE_MOBILE]
        self.context['request'].MOBILE = False
        self.context['request'].DESKTOP = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Expected: %r' % cls
        eq_(doc('.bad-app').length, 1)

    def test_can_install_tablet(self):
        self.webapp._device_types = [amo.DEVICE_TABLET]
        self.context['request'].MOBILE = False
        self.context['request'].TABLET = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_cannot_install_tablet_only(self):
        self.webapp._device_types = [amo.DEVICE_TABLET]
        self.context['request'].MOBILE = False
        self.context['request'].TABLET = False
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Expected: %r' % cls
        eq_(doc('.bad-app').length, 1)

    def test_can_install_firefoxos(self):
        self.webapp._device_types = [amo.DEVICE_GAIA]
        self.context['request'].MOBILE = True
        self.context['request'].TABLET = False
        self.context['request'].GAIA = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_cannot_install_firefoxos_only(self):
        self.webapp._device_types = [amo.DEVICE_GAIA]
        self.context['request'].MOBILE = False
        self.context['request'].TABLET = False
        self.context['request'].DESKTOP = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Expected: %r' % cls
        eq_(doc('.bad-app').length, 1)

    def test_can_install_packaged(self):
        self.webapp.is_packaged = True
        self.webapp._device_types = [amo.DEVICE_GAIA]
        self.context['request'].MOBILE = True
        self.context['request'].TABLET = False
        self.context['request'].GAIA = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' not in cls, 'Unexpected: %r' % cls
        eq_(doc('.bad-app').length, 0)

    def test_cannot_install_packaged(self):
        self.webapp.is_packaged = True
        self.webapp._device_types = [amo.DEVICE_GAIA]
        self.context['request'].MOBILE = False
        self.context['request'].TABLET = False
        self.context['request'].DESKTOP = True
        doc = pq(market_tile(self.context, self.webapp))
        cls = doc('button').attr('class')
        assert 'disabled' in cls, 'Expected: %r' % cls
        eq_(doc('.bad-app').length, 1)

    def test_xss(self):
        nasty = '<script>'
        escaped = '&lt;script&gt;'
        author = self.webapp.authors.all()[0]
        author.display_name = nasty
        author.save()

        self.webapp.name = nasty
        self.webapp.save()
        Webapp.transformer([self.webapp])  # Transform `listed_authors`, etc.

        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['name'], escaped)
        eq_(data['author'], escaped)

    def test_default_supported_currencies(self):
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        assert 'currencies' not in data

    @mock.patch('mkt.site.helpers.waffle.switch_is_active')
    def test_some_supported_currencies(self, switch_is_active):
        switch_is_active.return_value = True
        self.make_premium(self.webapp, currencies=['CAD'])
        ad = AddonPremium.objects.get(addon=self.webapp)
        ad.update(currencies=['USD', 'CAD'])
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(json.loads(data['currencies'])['USD'], '$1.00')
        eq_(json.loads(data['currencies'])['CAD'], 'CA$1.00')

    @mock.patch('access.acl.action_allowed')
    def test_reviewers(self, action_allowed):
        action_allowed.return_value = True
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        issue = urlparams(reverse('detail.record',
                                  args=[self.webapp.app_slug]), src='foo')
        eq_(data['recordUrl'], issue)

    def test_category(self):
        c = Category.objects.create(name='test-cat', type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=c)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['categories'],
            [str(cat.name) for cat in self.webapp.categories.all()])

    def test_install_src(self):
        # request.GET['src'] is 'foo', and we're overriding it.
        doc = pq(market_tile(self.context, self.webapp, src='xxx'))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['src'], 'xxx')

    @mock.patch.object(settings, 'SITE_URL', 'http://omg.org/yes')
    def test_is_packaged(self):

        self.webapp.is_packaged = True

        manifest_url = self.webapp.get_manifest_url()
        doc = pq(market_tile(self.context, self.webapp))
        # NOTE: PyQuery won't parse attributes with underscores
        # or uppercase letters.
        assert 'data-manifest_url="%s"' % manifest_url in doc.html()

        data = json.loads(doc('a').attr('data-product'))
        eq_(data['is_packaged'], True)
        eq_(data['manifest_url'], manifest_url)

    def test_is_not_packaged(self):
        manifest_url = self.webapp.manifest_url

        doc = pq(market_tile(self.context, self.webapp))
        assert 'data-manifest_url="%s"' % manifest_url in doc.html()

        data = json.loads(doc('a').attr('data-product'))
        eq_(data['is_packaged'], False)
        eq_(data['manifest_url'], manifest_url)

    def test_packaged_no_valid_status(self):
        self.webapp.is_packaged = True
        version = self.webapp.versions.latest()
        version.all_files[0].update(status=amo.STATUS_REJECTED)
        self.webapp.update_version()  # Reset cached `_current_version`.

        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('a').attr('data-product'))
        eq_(data['is_packaged'], True)
        eq_(data['manifest_url'], '')
        # The install button should not be shown if no current_version.
        eq_(doc('.product button').length, 0)


def test_login_link():
    request = mock.Mock()
    request.user = mock.Mock()
    request.user.is_authenticated.return_value = False
    request.GET = {}
    eq_(reverse('users.login'), get_login_link({'request': request}))

    request.GET = {'to': '/login'}
    eq_(reverse('users.login'), get_login_link({'request': request}))

    request.GET = {'to': 'foo'}
    eq_(urlparams(reverse('users.login'), to='foo'),
        get_login_link({'request': request}))
    eq_(urlparams(reverse('users.login'), to='bar'),
        get_login_link({'request': request}, 'bar'))

    request.user.is_authenticated.return_value = True
    eq_(get_login_link({'request': request}, to='foo'), 'foo')


class TestCSS(amo.tests.TestCase):

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', True)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_dev_unminified(self, fake_css):
        request = mock.Mock()
        request.GET = {}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_css.expects('css').with_args('mkt/consumer', False, True)
        css(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', False)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_prod_minified(self, fake_css):
        request = mock.Mock()
        request.GET = {}
        context = {'request': request}

        # Should be called with `debug=False`.
        fake_css.expects('css').with_args('mkt/consumer', False, False)
        css(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', True)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_dev_unminified_overridden(self, fake_css):
        request = mock.Mock()
        request.GET = {'debug': 'true'}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_css.expects('css').with_args('mkt/consumer', False, True)
        css(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', False)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_prod_unminified_overridden(self, fake_css):
        request = mock.Mock()
        request.GET = {'debug': 'true'}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_css.expects('css').with_args('mkt/consumer', False, True)
        css(context, 'mkt/consumer')


class TestJS(amo.tests.TestCase):

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', True)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_dev_unminified(self, fake_js):
        request = mock.Mock()
        request.GET = {}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_js.expects('js').with_args('mkt/consumer', True, False, False)
        js(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', False)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_prod_minified(self, fake_js):
        request = mock.Mock()
        request.GET = {}
        context = {'request': request}

        # Should be called with `debug=False`.
        fake_js.expects('js').with_args('mkt/consumer', False, False, False)
        js(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', True)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_dev_unminified_overridden(self, fake_js):
        request = mock.Mock()
        request.GET = {'debug': 'true'}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_js.expects('js').with_args('mkt/consumer', True, False, False)
        js(context, 'mkt/consumer')

    @mock.patch.object(settings, 'TEMPLATE_DEBUG', False)
    @fudge.patch('mkt.site.helpers.jingo_minify_helpers')
    def test_prod_unminified_overridden(self, fake_js):
        request = mock.Mock()
        request.GET = {'debug': 'true'}
        context = {'request': request}

        # Should be called with `debug=True`.
        fake_js.expects('js').with_args('mkt/consumer', True, False, False)
        js(context, 'mkt/consumer')
