# -*- coding: utf-8 -*-

from django.conf import settings

import fudge
import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse

from mkt.site.helpers import css, get_login_link, js


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
