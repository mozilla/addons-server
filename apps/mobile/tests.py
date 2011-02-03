# -*- coding: utf-8 -*-
from django import http, test
from django.conf import settings
from django.utils import http as urllib

from mobile import decorators, middleware


FENNEC = ('Mozilla/5.0 (Android; Linux armv7l; rv:2.0b8) '
          'Gecko/20101221 Firefox/4.0b8 Fennec/4.0b3')
FIREFOX = 'Mozilla/5.0 (Windows NT 5.1; rv:2.0b9) Gecko/20100101 Firefox/4.0b9'


class TestDetectMobile(test.TestCase):

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
            self.assertEqual(request.META['HTTP_X_MOBILE'], '1')
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


class TestXMobile(test.TestCase):

    def check(self, xmobile, mobile):
        request = test.RequestFactory().get('/')
        if xmobile:
            request.META['HTTP_X_MOBILE'] = xmobile
        middleware.XMobileMiddleware().process_request(request)
        self.assertEqual(request.MOBILE, mobile)

    def test_bad_xmobile(self):
        self.check(xmobile='xxx', mobile=False)

    def test_no_xmobile(self):
        self.check(xmobile=None, mobile=False)

    def test_xmobile_1(self):
        self.check(xmobile='1', mobile=True)

    def test_xmobile_0(self):
        self.check(xmobile='0', mobile=False)

    def test_vary(self):
        request = test.RequestFactory().get('/')
        response = http.HttpResponse()
        r = middleware.XMobileMiddleware().process_response(request, response)
        assert r is response
        self.assertEqual(response['Vary'], 'X-Mobile')

        response['Vary'] = 'User-Agent'
        middleware.XMobileMiddleware().process_response(request, response)
        self.assertEqual(response['Vary'], 'User-Agent, X-Mobile')


class TestMobilized(test.TestCase):

    def setUp(self):
        normal = lambda r: 'normal'
        mobile = lambda r: 'mobile'
        self.view = decorators.mobilized(normal)(mobile)
        self.request = test.RequestFactory().get('/')

    def test_call_normal(self):
        self.request.MOBILE = False
        self.assertEqual(self.view(self.request), 'normal')

    def test_call_mobile(self):
        self.request.MOBILE = True
        self.assertEqual(self.view(self.request), 'mobile')


class TestMobileTemplate(test.TestCase):

    def setUp(self):
        template = 'a/{mobile/}b.html'
        func = lambda request, template: template
        self.view = decorators.mobile_template(template)(func)
        self.request = test.RequestFactory().get('/')

    def test_normal_template(self):
        self.request.MOBILE = False
        self.assertEqual(self.view(self.request), 'a/b.html')

    def test_mobile_template(self):
        self.request.MOBILE = True
        self.assertEqual(self.view(self.request), 'a/mobile/b.html')
