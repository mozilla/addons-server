from django.http import HttpResponse

from nose.tools import eq_
from test_utils import RequestFactory

import amo.tests
from mkt.api.middleware import CORSMiddleware


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
