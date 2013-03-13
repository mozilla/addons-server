from django.conf import settings
from django.http import HttpResponse

import mock
from multidb import this_thread_is_pinned
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo.tests
from mkt.api.middleware import (APIPinningMiddleware, APITransactionMiddleware,
                                CORSMiddleware)
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
        eq_(res['Access-Control-Allow-Headers'], 'Content-Type')

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
        self.req.amo_user = mock.Mock()

    def test_pinned(self):
        self.req.amo_user.is_anonymous.return_value = False
        self.pin.process_request(self.req)
        ok_(this_thread_is_pinned())

    def test_not_pinned(self):
        self.req.amo_user.is_anonymous.return_value = True
        self.pin.process_request(self.req)
        ok_(not this_thread_is_pinned())
