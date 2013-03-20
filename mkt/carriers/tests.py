from django.conf import settings

import mock
from nose.tools import eq_
from test_utils import RequestFactory

from amo.tests import TestCase
from amo.urlresolvers import reverse, set_url_prefix

from . import get_carrier, set_carrier, context_processors
from .middleware import CarrierURLMiddleware


@mock.patch.object(settings, 'CARRIER_URLS', ['foostore'])
class TestCarrierURLs(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        set_carrier(None)
        set_url_prefix(None)

    def request(self, url):
        request = RequestFactory().get(url)
        # Simulate the RequestCookiesMiddleware.
        request.set_cookie = mock.Mock()
        return request

    def get(self, url, request=None):
        if not request:
            request = self.request(url)
        CarrierURLMiddleware().process_request(request)
        return request

    def test_strip_carrier(self):
        request = self.get('/foostore/foo')
        eq_(request.path_info, '/foo')
        assert request.set_cookie.called

    def test_ignore_non_carriers(self):
        request = self.get('/not-a-store')
        eq_(request.path_info, '/not-a-store')
        assert not request.set_cookie.called

    def test_set_carrier(self):
        request = self.get('/?carrier=foostore')
        eq_(get_carrier(), 'foostore')
        assert request.set_cookie.called

    def test_set_carrier_url(self):
        request = self.get('/foostore/')
        eq_(get_carrier(), 'foostore')
        assert request.set_cookie.called

    def test_set_carrier_none(self):
        request = self.request('/?carrier=')
        request.COOKIES = {'carrier': 'foostore'}
        request = self.get('/?carrier=', request)
        eq_(get_carrier(), None)
        assert request.set_cookie.called

    def test_set_carrer_to_none_url(self):
        self.get('/foostore/')
        self.get('/not-a-store')
        eq_(get_carrier(), None)

    def test_reverse(self):
        self.get('/foostore/')
        eq_(reverse('manifest.webapp'), '/manifest.webapp')

    def test_context(self):
        request = self.get('/foostore/')
        ctx = context_processors.carrier_data(request)
        eq_(ctx['CARRIER'], 'foostore')

    def test_root_url(self):
        request = self.get('/?carrier=foostore')
        eq_(request.path_info, '/')
