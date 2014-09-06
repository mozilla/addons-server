import mock
from nose.tools import eq_
from test_utils import RequestFactory
from elasticsearch import TransportError

import amo.tests
from search.middleware import ElasticsearchExceptionMiddleware as ESM


class TestElasticsearchExceptionMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.request = RequestFactory()

    @mock.patch('search.middleware.render')
    def test_exceptions_we_catch(self, render_mock):
        ESM().process_exception(self.request, TransportError(400, 'ES ERROR'))
        render_mock.assert_called_with(self.request, 'search/down.html',
                                       status=503)
        render_mock.reset_mock()

    @mock.patch('search.middleware.render')
    def test_exceptions_we_do_not_catch(self, render_mock):
        ESM().process_exception(self.request, Exception)
        eq_(render_mock.called, False)
