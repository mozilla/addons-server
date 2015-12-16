# -*- coding: utf-8 -*-
from django import http, test
from django.conf import settings
from django.test.client import RequestFactory

import pytest
from commonware.middleware import ScrubRequestOnException
from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase

from olympia.amo.middleware import NoAddonsMiddleware, NoVarySessionMiddleware
from olympia.amo.urlresolvers import reverse
from olympia.zadmin.models import Config


pytestmark = pytest.mark.django_db


class TestMiddleware(TestCase):

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
    response = test.Client().get(
        '/da/firefox/addon/5457?from=/da/firefox/'
        'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
        '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
        'E3%82%BA')
    eq_(response.status_code, 301)
    assert 'utm_term=Google+%E3%83%90%E3%82%BA' in response['Location']


def test_source_with_wrong_unicode_get():
    # The following url is a string (bytes), not unicode.
    response = test.Client().get('/firefox/collections/mozmj/autumn/'
                                 '?source=firefoxsocialmedia\x14\x85')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('?source=firefoxsocialmedia%14')


def test_trailing_slash_middleware():
    response = test.Client().get(u'/en-US/about/?xxx=\xc3')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('/en-US/about?xxx=%C3%83')


class AdminMessageTest(TestCase):

    def test_message(self):
        c = Config.objects.create(key='site_notice', value='ET Sighted.')

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(doc('#site-notice').text(), 'ET Sighted.')

        c.delete()

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


class TestNoAddonsMiddleware(TestCase):

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


class TestNoDjangoDebugToolbar(TestCase):
    """Make sure the Django Debug Toolbar isn't available when DEBUG=False."""

    def test_no_django_debug_toolbar(self):
        with self.settings(DEBUG=False):
            res = self.client.get(reverse('home'), follow=True)
            assert 'djDebug' not in res.content
            assert 'debug_toolbar' not in res.content
