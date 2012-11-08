import mock
from nose.tools import eq_

from django.http import HttpResponse

import amo.tests
from mkt.fragments.utils import bust_fragments


class BustFragmentCacheCase(object):

    def setUp(self):
        self.req = mock.Mock()
        self.req.method = 'POST'

        self.resp = HttpResponse()
        self.resp.status_code = 200

        self.req.response = self.resp

    def assert_header_not_set(self):
        assert 'x-frag-bust' not in self.resp

    def assert_header_set(self, value):
        eq_(self.resp['x-frag-bust'], value)


class TestBustFragmentCache(BustFragmentCacheCase):

    def test_min_args(self):
        """Assert that bust_fragments applies with the minimum args."""
        bust_fragments(self.resp, '/foo/bar')
        self.assert_header_set('["/foo/bar"]')

    def test_list(self):
        """Assert that bust_fragments applies a list properly."""
        bust_fragments(self.resp, ['/foo/bar', '/zip/zap'])
        self.assert_header_set('["/foo/bar", "/zip/zap"]')

    def test_formatted_prefix(self):
        """Assert that bust_fragments formats (kw)?args into the URLs ok."""
        bust_fragments(self.resp, '/foo/{1}/{asdf}', 'first', 'second',
                       asdf='kw')
        self.assert_header_set('["/foo/second/kw"]')
