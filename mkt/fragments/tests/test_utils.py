import mock

import amo.tests
from mkt.fragments.utils import bust_fragments


class BustFragmentCacheCase(object):

    def setUp(self):
        self.req = mock.Mock()
        self.req.method = 'POST'

        self.resp = mock.Mock()
        self.resp.status_code = 200

        self.req.response = self.resp

    def assert_cookie_not_set(self):
        assert not self.resp.set_cookie.called

    def assert_cookie_set(self, value):
        self.resp.set_cookie.assert_called_with('fcbust', value)


class TestBustFragmentCache(BustFragmentCacheCase):

    def test_min_args(self):
        """Assert that bust_fragments applies with the minimum args."""
        bust_fragments(self.resp, '/foo/bar')
        self.assert_cookie_set('["/foo/bar"]')

    def test_list(self):
        """Assert that bust_fragments applies a list properly."""
        bust_fragments(self.resp, ['/foo/bar', '/zip/zap'])
        self.assert_cookie_set('["/foo/bar", "/zip/zap"]')

    def test_formatted_prefix(self):
        """Assert that bust_fragments formats (kw)?args into the URLs ok."""
        bust_fragments(self.resp, '/foo/{1}/{asdf}', 'first', 'second',
                       asdf='kw')
        self.assert_cookie_set('["/foo/second/kw"]')
