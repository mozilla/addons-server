# -*- coding: utf-8 -*-
from django import http, test
from django.conf import settings
from django.utils import http as urllib

import mock
import test_utils
from nose.tools import eq_

from mobile import decorators, middleware


FENNEC = ('Mozilla/5.0 (Android; Linux armv7l; rv:2.0b8) '
          'Gecko/20101221 Firefox/4.0b8 Fennec/4.0b3')
FIREFOX = 'Mozilla/5.0 (Windows NT 5.1; rv:2.0b9) Gecko/20100101 Firefox/4.0b9'


class TestDetectMobile(test_utils.TestCase):

    def check(self, mobile, ua=None, cookie=None):
        d = {}
        if cookie:
            d['HTTP_COOKIE'] = 'mamo=%s' % cookie
        if ua:
            d['HTTP_USER_AGENT'] = ua
        request = test.RequestFactory().get('/', **d)
        response = middleware.DetectMobileMiddleware().process_request(request)
        assert response is None
        if mobile:
            eq_(request.META['HTTP_X_MOBILE'], '1')
        else:
            assert 'HTTP_X_MOBILE' not in request.META

    def test_mobile_ua(self):
        self.check(mobile=True, ua=FENNEC)

    def test_mobile_ua_and_cookie_on(self):
        self.check(mobile=True, ua=FENNEC, cookie='on')

    def test_mobile_ua_and_cookie_off(self):
        self.check(mobile=False, ua=FENNEC, cookie='off')

    def test_nonmobile_ua(self):
        self.check(mobile=False, ua=FIREFOX)

    def test_nonmobile_ua_and_cookie_on(self):
        self.check(mobile=True, ua=FIREFOX, cookie='on')

    def test_nonmobile_ua_and_cookie_off(self):
        self.check(mobile=False, ua=FIREFOX, cookie='off')

    def test_no_ua(self):
        self.check(mobile=False)


class TestXMobile(test_utils.TestCase):

    def setUp(self):
        self.middleware = middleware.XMobileMiddleware()
        self.view = decorators.mobilized(lambda: 1)(lambda: 1)

    def check(self, domain, xmobile, redirect, path='/', query=None):
        url = path
        if query:
            url += '?' + query
        request = test.RequestFactory().get(url)
        request.META['SERVER_NAME'] = domain
        if xmobile:
            request.META['HTTP_X_MOBILE'] = xmobile
        response = self.middleware.process_view(request, self.view, (), {})
        if redirect:
            eq_(response.status_code, 301)
            url = redirect + urllib.urlquote(path)
            if query:
                url += '?' + query
            eq_(response['Location'], url)
            eq_(response['Vary'], 'X-Mobile')
        else:
            eq_(request.MOBILE, xmobile == '1')

    def test_bad_xmobile_on_mamo(self):
        self.check(settings.MOBILE_DOMAIN, xmobile='adfadf',
                   redirect=settings.SITE_URL)

    def test_no_xmobile_on_mamo(self):
        self.check(settings.MOBILE_DOMAIN, xmobile=None,
                   redirect=settings.SITE_URL)

    def test_no_xmobile_on_amo(self):
        self.check(settings.DOMAIN, xmobile=None, redirect=False)

    def test_xmobile_0_on_mamo(self):
        self.check(settings.MOBILE_DOMAIN, xmobile='0',
                   redirect=settings.SITE_URL)

    def test_xmobile_1_on_mamo(self):
        self.check(settings.MOBILE_DOMAIN, xmobile='1', redirect=False)

    def test_xmobile_1_on_mamo_nonbmobile_function(self):
        self.view.mobile = False
        self.check(settings.MOBILE_DOMAIN, xmobile='1',
                   redirect=settings.SITE_URL)
        self.view = lambda: 1
        self.check(settings.MOBILE_DOMAIN, xmobile='1',
                   redirect=settings.SITE_URL)

    def test_xmobile_0_on_amo(self):
        self.check(settings.DOMAIN, xmobile='0', redirect=False)

    def test_xmobile_1_on_amo(self):
        self.check(settings.DOMAIN, xmobile='1',
                   redirect=settings.MOBILE_SITE_URL)

    def test_xmobile_1_on_amo_nonmobile_function(self):
        # The function could have mobile=False or undefined.
        self.view.mobile = False
        self.check(settings.DOMAIN, xmobile='1', redirect=False)
        self.view = lambda: 1
        self.check(settings.DOMAIN, xmobile='1', redirect=False)

    def test_redirect_unicode_path(self):
        path = u'/el/addon/Ελληνικά/'
        self.check(settings.DOMAIN, xmobile='1',
                   redirect=settings.MOBILE_SITE_URL, path=path)

    def test_redirect_unicode_query(self):
        query = 'uu=e+%E3%83%90%E3%82%BA&ff=2'
        self.check(settings.DOMAIN, xmobile='1',
                   redirect=settings.MOBILE_SITE_URL, query=query)

    def test_redirect_preserve_get(self):
        query = 'q=1'
        self.check(settings.DOMAIN, xmobile='1',
                   redirect=settings.MOBILE_SITE_URL, query=query)

    def test_vary(self):
        request = test.RequestFactory().get('/')
        response = http.HttpResponse()
        r = self.middleware.process_response(request, response)
        assert r is response
        eq_(response['Vary'], 'X-Mobile')

        response['Vary'] = 'User-Agent'
        self.middleware.process_response(request, response)
        eq_(response['Vary'], 'User-Agent, X-Mobile')


class TestMobilized(object):

    def setUp(self):
        normal = lambda r: 'normal'
        mobile = lambda r: 'mobile'
        self.view = decorators.mobilized(normal)(mobile)
        self.request = mock.Mock()

    def test_mobile_attr(self):
        eq_(self.view.mobile, True)

    def test_call_normal(self):
        self.request.MOBILE = False
        eq_(self.view(self.request), 'normal')

    def test_call_mobile(self):
        self.request.MOBILE = True
        eq_(self.view(self.request), 'mobile')
