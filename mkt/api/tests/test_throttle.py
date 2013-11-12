from django.test.client import RequestFactory

from mock import patch
from tastypie.exceptions import ImmediateHttpResponse

from mkt.api.base import HttpTooManyRequests, MarketplaceResource
from mkt.api.tests.test_oauth import BaseOAuth


class ThrottleTests(object):
    """
    Mixin to add tests that ensure API endpoints are being appropriately
    throttled.

    Note: subclasses will need to define the resource being tested.
    """
    resource = None
    request = RequestFactory().post('/')

    def test_should_throttle(self):
        if not self.resource:
            return

        with patch.object(self.resource._meta, 'throttle') as throttle:
            throttle.should_be_throttled.return_value = True
            with self.assertImmediate(HttpTooManyRequests):
                self.resource.throttle_check(self.request)

    def test_shouldnt_throttle(self):
        with patch.object(self, 'resource') as resource:
            resource._meta.throttle.should_be_throttled.return_value = False
            try:
                self.resource.throttle_check(self.request)
            except ImmediateHttpResponse:
                self.fail('Unthrottled request raises ImmediateHttpResponse')


class TestThrottle(ThrottleTests, BaseOAuth):
    resource = MarketplaceResource()
