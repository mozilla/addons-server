from urlparse import parse_qs

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseServerError

import mock
from multidb import this_thread_is_pinned
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo.tests
from mkt.api.middleware import (APIFilterMiddleware, APIPinningMiddleware,
                                APITransactionMiddleware, APIVersionMiddleware,
                                CORSMiddleware)
import mkt.regions
from mkt.site.middleware import RedirectPrefixedURIMiddleware

fireplace_url = 'http://firepla.ce:1234'


class TestCORS(amo.tests.TestCase):

    def setUp(self):
        self.mware = CORSMiddleware()
        self.req = RequestFactory().get('/')

    def test_not_cors(self):
        res = self.mware.process_response(self.req, HttpResponse())
        assert not res.has_header('Access-Control-Allow-Methods')

    def test_cors(self):
        self.req.CORS = ['get']
        res = self.mware.process_response(self.req, HttpResponse())
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')

    def test_post(self):
        self.req.CORS = ['get', 'post']
        res = self.mware.process_response(self.req, HttpResponse())
        eq_(res['Access-Control-Allow-Methods'], 'GET, POST, OPTIONS')
        eq_(res['Access-Control-Allow-Headers'],
            'X-HTTP-Method-Override, Content-Type')

    @mock.patch.object(settings, 'FIREPLACE_URL', fireplace_url)
    def test_from_fireplace(self):
        self.req.CORS = ['get']
        self.req.META['HTTP_ORIGIN'] = fireplace_url
        res = self.mware.process_response(self.req, HttpResponse())
        eq_(res['Access-Control-Allow-Origin'], fireplace_url)
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')
        eq_(res['Access-Control-Allow-Credentials'], 'true')


class TestTransactionMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.prefix = RedirectPrefixedURIMiddleware()
        self.transaction = APITransactionMiddleware()

    def test_api(self):
        req = RequestFactory().get('/api/foo/')
        self.prefix.process_request(req)
        ok_(req.API)

    def test_not_api(self):
        req = RequestFactory().get('/not-api/foo/')
        self.prefix.process_request(req)
        ok_(not req.API)

    @mock.patch('django.db.transaction.enter_transaction_management')
    def test_transactions(self, enter):
        req = RequestFactory().get('/api/foo/')
        self.prefix.process_request(req)
        self.transaction.process_request(req)
        ok_(enter.called)

    @mock.patch('django.db.transaction.enter_transaction_management')
    def test_not_transactions(self, enter):
        req = RequestFactory().get('/not-api/foo/')
        self.prefix.process_request(req)
        self.transaction.process_request(req)
        ok_(not enter.called)


class TestPinningMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.pin = APIPinningMiddleware()
        self.req = RequestFactory().get('/')
        self.req.API = True
        self.key = 'api-pinning:42'

    def attach_user(self, anon=True):
        self.req.amo_user = mock.Mock(id=42, is_anonymous=lambda: anon)

    def test_pinned_request_method(self):
        self.attach_user(anon=False)

        for method in ['DELETE', 'PATCH', 'POST', 'PUT']:
            self.req.method = method
            self.pin.process_request(self.req)
            ok_(this_thread_is_pinned())

        for method in ['GET', 'HEAD', 'OPTIONS', 'POOP']:
            self.req.method = method
            self.pin.process_request(self.req)
            ok_(not this_thread_is_pinned())

    def test_pinned_cached(self):
        cache.set(self.key, 1, 5)
        self.attach_user(anon=False)
        self.pin.process_request(self.req)
        ok_(this_thread_is_pinned())
        cache.delete(self.key)

    def test_not_pinned(self):
        self.attach_user(anon=True)
        self.pin.process_request(self.req)
        ok_(not this_thread_is_pinned())

    def test_process_response_anon(self):
        self.attach_user(anon=True)
        self.req.method = 'POST'
        self.pin.process_response(self.req, HttpResponse())
        ok_(not cache.get(self.key))

    def test_process_response(self):
        self.attach_user(anon=False)
        for method in ['DELETE', 'PATCH', 'POST', 'PUT']:
            self.req.method = method
            self.pin.process_response(self.req, HttpResponse())
            ok_(cache.get(self.key))
            cache.delete(self.key)

        for method in ['GET', 'HEAD', 'OPTIONS', 'POOP']:
            self.req.method = method
            self.pin.process_response(self.req, HttpResponse())
            ok_(not cache.get(self.key))


class TestAPIVersionMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.dep = APIVersionMiddleware()

    def req(self, url, header):
        req = RequestFactory().get(url)
        self.dep.process_request(req)
        res = self.dep.process_response(req, HttpResponse())
        return res.get(header, None)

    def test_notice(self):
        eq_(self.req('/foo/', 'API-Status'), None)
        eq_(self.req('/foo/api/', 'API-Status'), None)
        eq_(self.req('/api/', 'API-Status'), 'Deprecated')
        eq_(self.req('/api/v1/', 'API-Status'), None)
        eq_(self.req('/api/v1/', 'API-Version'), '1')


class TestFilterMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.middleware = APIFilterMiddleware()
        self.factory = RequestFactory()

    def _header(self, url='/', api=True, region=mkt.regions.US, lang='en-US',
                gaia=True, tablet=True, mobile=True, pro='8a7d546c.32.1',
                response_cls=HttpResponse):
        self.request = self.factory.get(url, {'pro': pro})
        self.request.API = api
        self.request.REGION = region
        self.request.LANG = lang or ''
        self.request.GAIA = gaia
        self.request.TABLET = tablet
        self.request.MOBILE = mobile
        res = self.middleware.process_response(self.request, response_cls())
        if api and response_cls.status_code < 500:
            header = res.get('API-Filter')
            assert 'vary' in res._headers
            eq_(res._headers['vary'][1], 'API-Filter')
            self._test_order(header)
            return parse_qs(header)
        else:
            assert 'vary' not in res._headers
            return None

    def _test_order(self, header):
        order = [item.split('=')[0] for item in header.split('&')]
        eq_(order, sorted(order))

    @mock.patch('mkt.api.middleware.get_carrier')
    def test_success(self, gc):
        carrier = 'telerizon'
        gc.return_value = carrier
        header = self._header()
        self.assertIsInstance(header, dict)
        assert mkt.regions.US.slug in header['region']
        assert 'en-US' in header['lang']
        assert '8a7d546c.32.1' in header['pro']
        assert carrier in header['carrier']
        self.assertSetEqual(['gaia', 'mobile', 'tablet'], header['device'])

    def test_api_false(self):
        header = self._header(api=False)
        eq_(header, None)

    def test_no_devices(self):
        header = self._header(gaia=False, tablet=False, mobile=False)
        assert 'device' not in header

    def test_one_device(self):
        header = self._header(gaia=True, tablet=False, mobile=False)
        self.assertSetEqual(['gaia'], header['device'])

    @mock.patch('mkt.api.middleware.get_carrier')
    def test_no_carrier(self, gc):
        gc.return_value = None
        header = self._header()
        assert 'carrier' not in header

    def test_region(self):
        region = mkt.regions.BR
        header = self._header(region=region)
        assert region.slug in header['region']

    def test_no_region(self):
        with self.assertRaises(AttributeError):
            self._header(region=None)

    def test_lang(self):
        lang = 'pt-BR'
        header = self._header(lang=lang)
        assert lang in header['lang']

    def test_no_lang(self):
        header = self._header(lang=None)
        assert 'lang' not in header

    def test_500(self):
        self._header(response_cls=HttpResponseServerError)
