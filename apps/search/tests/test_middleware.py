import jingo
import mock
from nose.tools import eq_
from pyes.exceptions import ElasticSearchException, IndexMissingException
from pyes.urllib3.connectionpool import HTTPError, MaxRetryError, TimeoutError
from test_utils import RequestFactory

import amo.tests
from search.middleware import ElasticsearchExceptionMiddleware as ESM


class TestElasticsearchExceptionMiddleware(amo.tests.TestCase):

    def setUp(self):
        self.request = RequestFactory()

    @mock.patch.object(jingo, 'render')
    def test_exceptions_we_catch(self, jingo_mock):
        # These are instantiated with an error string.
        for e in [ElasticSearchException, IndexMissingException]:
            ESM().process_exception(self.request, e('ES ERROR'))
            jingo_mock.assert_called_with(self.request, 'search/down.html',
                                          status=503)
            jingo_mock.reset_mock()

        # These are just Exception classes.
        for e in [HTTPError, MaxRetryError, TimeoutError]:
            ESM().process_exception(self.request, e('ES ERROR'))
            jingo_mock.assert_called_with(self.request, 'search/down.html',
                                          status=503)
            jingo_mock.reset_mock()

    @mock.patch.object(jingo, 'render')
    def test_exceptions_we_do_not_catch(self, jingo_mock):
        ESM().process_exception(self.request, Exception)
        eq_(jingo_mock.called, False)
