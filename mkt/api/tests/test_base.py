from tastypie import http
from tastypie.authorization import Authorization
from test_utils import RequestFactory

from amo.tests import TestCase
from mkt.api.base import MarketplaceResource


class TestMarketplace(TestCase):
    def setUp(self):
        self.resource = MarketplaceResource()
        self.resource._meta.authorization = Authorization()
        self.request = RequestFactory().post('/')

    def test_form_encoded(self):
        """
        Regression test of bug #858403: ensure that a 400 (and not 500) is
        raised when an unsupported Content-Type header is passed to an API
        endpoint.
        """
        self.request.META['CONTENT_TYPE'] = 'application/x-www-form-urlencoded'
        with self.assertImmediate(http.HttpBadRequest):
            self.resource.dispatch('list', self.request)
