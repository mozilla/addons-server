from django.test.client import RequestFactory

from mock import patch
from tastypie.exceptions import ImmediateHttpResponse

from mkt.api.base import HttpTooManyRequests, MarketplaceResource
from mkt.api.tests.test_oauth import BaseOAuth


class TestThrottle(BaseOAuth):

    def setUp(self):
        super(TestThrottle, self).setUp()
        self.resource = MarketplaceResource()
        self.request = RequestFactory().get('/')

    @patch('tastypie.throttle.BaseThrottle.should_be_throttled')
    def test_should_throttle(self, should_be_throttled):
        should_be_throttled.return_value = True
        with self.assertImmediate(HttpTooManyRequests):
            self.resource.throttle_check(self.request)

    def test_shouldnt_throttle(self):
        try:
            self.resource.throttle_check(self.request)
        except ImmediateHttpResponse:
            self.fail('Unthrottled request raises ImmediateHttpResponse')
