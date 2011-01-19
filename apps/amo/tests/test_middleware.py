# -*- coding: utf-8 -*-
from django import http, test
from django.conf import settings
from django.utils import http as urllib

from commonware.middleware import HidePasswordOnException
from nose.tools import eq_
from pyquery import PyQuery as pq
from test_utils import TestCase, RequestFactory

from amo import middleware
from amo.urlresolvers import reverse
from zadmin.models import Config, _config_cache

FENNEC = ('Mozilla/5.0 (Android; Linux armv7l; rv:2.0b8) '
          'Gecko/20101221 Firefox/4.0b8 Fennec/4.0b3')
FIREFOX = 'Mozilla/5.0 (Windows NT 5.1; rv:2.0b9) Gecko/20100101 Firefox/4.0b9'


def test_no_vary_cookie():
    # We don't break good usage of Vary.
    response = test.Client().get('/')
    eq_(response['Vary'], 'Accept-Language, User-Agent, X-Mobile')

    # But we do prevent Vary: Cookie.
    response = test.Client().get('/', follow=True)
    eq_(response['Vary'], 'X-Mobile')


def test_redirect_with_unicode_get():
    response = test.Client().get('/da/firefox/addon/5457?from=/da/firefox/'
            'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
            '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
            'E3%82%BA')
    eq_(response.status_code, 301)


def test_trailing_slash_middleware():
    response = test.Client().get(u'/en-US/firefox/about/?xxx=\xc3')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('/en-US/firefox/about?xxx=%C3%83')


class AdminMessageTest(TestCase):
    def test_message(self):
        c = Config()
        c.key = 'site_notice'
        c.value = 'ET Sighted.'
        c.save()

        if ('site_notice',) in _config_cache:
            del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(doc('#site-notice').text(), 'ET Sighted.')

        c.delete()

        del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(len(doc('#site-notice')), 0)


def test_hide_password_middleware():
    request = RequestFactory().post('/', dict(x=1, password=2, password2=2))
    request.POST._mutable = False
    HidePasswordOnException().process_exception(request, Exception())
    eq_(request.POST['x'], '1')
    eq_(request.POST['password'], '******')
    eq_(request.POST['password2'], '******')


class TestMobile(TestCase):

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


class TestXMobile(TestCase):

    def setUp(self):
        self.middleware = middleware.XMobileMiddleware()

    def check(self, domain, xmobile, redirect, path='/', query=None):
        url = path
        if query:
            url += '?' + query
        request = test.RequestFactory().get(url)
        request.META['SERVER_NAME'] = domain
        if xmobile:
            request.META['HTTP_X_MOBILE'] = xmobile
        response = self.middleware.process_request(request)
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

    def test_xmobile_0_on_amo(self):
        self.check(settings.DOMAIN, xmobile='0', redirect=False)

    def test_xmobile_1_on_amo(self):
        self.check(settings.DOMAIN, xmobile='1',
                   redirect=settings.MOBILE_SITE_URL)

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
