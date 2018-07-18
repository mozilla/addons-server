from django.test.client import RequestFactory

import mock

from elasticsearch import TransportError

from olympia.amo.tests import TestCase
from olympia.search.middleware import ElasticsearchExceptionMiddleware as ESM


class TestElasticsearchExceptionMiddleware(TestCase):
    def setUp(self):
        super(TestElasticsearchExceptionMiddleware, self).setUp()
        self.request = RequestFactory()

    @mock.patch('olympia.search.middleware.render')
    def test_exceptions_we_catch(self, render_mock):
        ESM().process_exception(self.request, TransportError(400, 'ES ERROR'))
        render_mock.assert_called_with(
            self.request, 'search/down.html', status=503
        )
        render_mock.reset_mock()

    @mock.patch('olympia.search.middleware.render')
    def test_exceptions_we_do_not_catch(self, render_mock):
        ESM().process_exception(self.request, Exception)
        assert not render_mock.called
