# -*- coding: utf-8 -*-
from django import http, test
from django.conf import settings

from commonware.middleware import ScrubRequestOnException
from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo.tests
from amo.middleware import NoAddonsMiddleware, NoVarySessionMiddleware
from amo.urlresolvers import reverse
from zadmin.models import Config, _config_cache


class TestMiddleware(amo.tests.TestCase):

    def test_no_vary_cookie(self):
        # We don't break good usage of Vary.
        response = test.Client().get('/')
        eq_(response['Vary'], 'Accept-Language, User-Agent, X-Mobile')

        # But we do prevent Vary: Cookie.
        response = test.Client().get('/', follow=True)
        eq_(response['Vary'], 'X-Mobile, User-Agent')

    @patch('django.contrib.sessions.middleware.'
           'SessionMiddleware.process_request')
    def test_session_not_used_api(self, process_request):
        req = RequestFactory().get('/')
        req.API = True
        NoVarySessionMiddleware().process_request(req)
        assert not process_request.called

    @patch('django.contrib.sessions.middleware.'
           'SessionMiddleware.process_request')
    def test_session_not_used(self, process_request):
        req = RequestFactory().get('/')
        NoVarySessionMiddleware().process_request(req)
        assert process_request.called


def test_redirect_with_unicode_get():
    response = test.Client().get('/da/firefox/addon/5457?from=/da/firefox/'
            'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
            '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
            'E3%82%BA')
    eq_(response.status_code, 301)


def test_trailing_slash_middleware():
    response = test.Client().get(u'/en-US/about/?xxx=\xc3')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('/en-US/about?xxx=%C3%83')


class AdminMessageTest(amo.tests.TestCase):

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
    ScrubRequestOnException().process_exception(request, Exception())
    eq_(request.POST['x'], '1')
    eq_(request.POST['password'], '******')
    eq_(request.POST['password2'], '******')


class TestNoAddonsMiddleware(amo.tests.TestCase):

    @patch('amo.middleware.ViewMiddleware.get_name')
    def process(self, name, get_name):
        get_name.return_value = name
        request = RequestFactory().get('/')
        view = Mock()
        return NoAddonsMiddleware().process_view(request, view, [], {})

    @patch.object(settings, 'NO_ADDONS_MODULES',
                  ('some.addons',))
    def test_middleware(self):
        self.assertRaises(http.Http404, self.process, 'some.addons')
        self.assertRaises(http.Http404, self.process, 'some.addons.thingy')
        assert not self.process('something.else')
