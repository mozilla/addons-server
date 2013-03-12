from django.http import HttpResponse

import mock
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo.tests
from mkt.api.middleware import APITransactionMiddleware, CORSMiddleware
from mkt.site.middleware import RedirectPrefixedURIMiddleware


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
