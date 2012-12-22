from django.conf import settings
from django.http import HttpResponse

import mock
from nose.exc import SkipTest
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
        if not settings.USE_CARRIER_URLS:
            raise SkipTest()
        set_carrier(None)
        set_url_prefix(None)

    def get(self, url):
        request = RequestFactory().get(url)
        CarrierURLMiddleware().process_request(request)
        return request

    def test_strip_carrier(self):
        request = self.get('/foostore/foo')
        eq_(request.path_info, '/foo')

    @mock.patch.object(settings, 'APPEND_SLASH', True)
    def test_root_url_ensures_slash(self):
        request = RequestFactory().get('/foostore')
        response = CarrierURLMiddleware().process_request(request)
        eq_(response['Location'], '/foostore/')

    def test_ignore_non_carriers(self):
        request = self.get('/not-a-store')
        eq_(request.path_info, '/not-a-store')

    def test_set_carrier(self):
        self.get('/foostore/')
        eq_(get_carrier(), 'foostore')

    def test_set_carrer_to_none(self):
        self.get('/foostore/')  # should be overriden
        self.get('/not-a-store')
        eq_(get_carrier(), None)

    def test_reverse(self):
        self.get('/foostore/')
        eq_(reverse('manifest.webapp'), '/foostore/manifest.webapp')

    def test_context(self):
        request = self.get('/foostore/')
        ctx = context_processors.carrier_data(request)
        eq_(ctx['CARRIER'], 'foostore')

    def test_slash_redirects_work(self):
        self.assertRedirects(self.client.get('/foostore/developers'),
                             '/foostore/developers/', status_code=301)

    def test_logout_preserves_carrier(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        response = self.client.get('/foostore' + reverse('users.logout'))
        self.assertRedirects(response, '/foostore/')
