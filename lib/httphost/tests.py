import unittest

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test.client import RequestFactory

import mock
from nose.tools import raises, eq_

from lib import httphost
from lib.httphost.context_processors import httphost_context
from lib.httphost.middleware import HTTPHostMiddleware


class UninitializedApp:
    """stub for httphost.app"""


class TestHTTPHost(unittest.TestCase):

    def middleware(self, http_host):
        serv = RequestFactory()
        req = serv.get('/some/url')
        req.META['HTTP_HOST'] = http_host
        mw = HTTPHostMiddleware()
        mw.process_request(req)

    def context(self):
        serv = RequestFactory()
        return httphost_context(serv.get('/some/url'))

    @mock.patch('lib.httphost.httphost.app', UninitializedApp)
    @raises(RuntimeError)
    def test_not_set(self):
        httphost.site_url()

    def test_site_url(self):
        self.middleware('telefonica.marketplace.mozilla.org')
        eq_(httphost.site_url(),
            'https://telefonica.marketplace.mozilla.org')

    @mock.patch.object(settings, 'DEBUG', True)
    @mock.patch.object(settings, 'SITE_URL_OVERRIDE',
                       'http://localhost:8000')
    def test_site_url_override(self):
        self.middleware('telefonica.marketplace.mozilla.org')
        eq_(httphost.site_url(), 'http://localhost:8000')

    @raises(ImproperlyConfigured)
    @mock.patch.object(settings, 'DEBUG', False)
    @mock.patch.object(settings, 'SITE_URL_OVERRIDE',
                       'http://localhost:8000')
    def test_cannot_override_site_url_in_prod(self):
        httphost.site_url()

    def test_subdomain(self):
        self.middleware('telefonica.marketplace.mozilla.org')
        eq_(httphost.subdomain(), 'telefonica')

    def test_subdomain_amo(self):
        self.middleware('addons.mozilla.org')
        eq_(httphost.subdomain(), 'addons')

    @mock.patch('lib.httphost.httphost.app', UninitializedApp)
    @raises(RuntimeError)
    def test_subdomain_not_set(self):
        httphost.subdomain()

    def test_subdomain_context(self):
        self.middleware('telefonica.marketplace.mozilla.org')
        eq_(self.context()['SUBDOMAIN'], 'telefonica')

    def test_site_url_context(self):
        self.middleware('marketplace.mozilla.org')
        eq_(self.context()['SITE_URL'], 'https://marketplace.mozilla.org')

    def test_site_url_is_scrubbed(self):
        self.middleware('file:///etc/passwd')
        eq_(httphost.site_url(), 'https://fileetcpasswd')

    def test_subdomain_is_scrubbed(self):
        self.middleware('file:///etc/passwd')
        eq_(httphost.subdomain(), 'fileetcpasswd')
