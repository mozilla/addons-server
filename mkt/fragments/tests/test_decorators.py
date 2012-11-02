from nose.tools import raises

import amo.tests
from mkt.fragments.decorators import bust_fragments_on_post

from test_utils import BustFragmentCacheCase


def dummy_view(request, *args, **kwargs):
    return request.response


def static_bfop(*args, **kwargs):
    decorated = bust_fragments_on_post(*args, **kwargs)(dummy_view)
    return staticmethod(decorated)


class TestBustFragmentCacheDecorator(BustFragmentCacheCase):

    meth_str_prefix = static_bfop(url_prefix='/foo/bar')
    meth_list_prefix = static_bfop(url_prefix=['/foo/bar', '/zip/zap'])
    meth_2xx_prefix = static_bfop(
        url_prefix='/foo/bar', bust_on_2xx=True, bust_on_3xx=False)
    meth_3xx_prefix = static_bfop(
        url_prefix='/foo/bar', bust_on_2xx=False, bust_on_3xx=True)

    def test_post(self):
        """Assert that bust_fragments_on_post only applies on POST."""
        self.meth_str_prefix(self.req)
        self.assert_cookie_set('["/foo/bar"]')

    def test_not_post(self):
        """Assert that bust_fragments_on_post only applies on POST."""
        self.req.method = 'GET'
        self.meth_str_prefix(self.req)
        self.assert_cookie_not_set()

    def test_not_weird_status_code(self):
        """
        Assert that bust_fragments_on_post doesn't apply to bad status codes.
        """
        self.resp.status_code = 404
        self.meth_str_prefix(self.req)
        self.assert_cookie_not_set()

    def test_list_post(self):
        """Test that a list is correctly encoded for busting."""
        self.meth_list_prefix(self.req)
        self.assert_cookie_set('["/foo/bar", "/zip/zap"]')

    def test_only_2xx(self):
        self.meth_2xx_prefix(self.req)
        self.assert_cookie_set('["/foo/bar"]')

    def test_only_3xx(self):
        self.resp.status_code = 301
        self.meth_3xx_prefix(self.req)
        self.assert_cookie_set('["/foo/bar"]')

    def test_not_2xx(self):
        self.resp.status_code = 301
        self.meth_2xx_prefix(self.req)
        self.assert_cookie_not_set()

    def test_not_3xx(self):
        self.meth_3xx_prefix(self.req)
        self.assert_cookie_not_set()

    meth_formatted_prefix = static_bfop(url_prefix='/foo/{1}/{asdf}')

    def test_formatted_prefix(self):
        self.meth_formatted_prefix(self.req, 'first', 'second', asdf='kw')
        self.assert_cookie_set('["/foo/second/kw"]')

    @raises(AssertionError)
    def test_decorator_order(self):
        # Give it something that's not a URL-safe type (e.g.: `self`).
        self.meth_str_prefix(self.req, foo=self)
