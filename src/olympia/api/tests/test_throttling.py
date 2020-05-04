import mock

from django.conf import settings
from django.test.client import RequestFactory
from django.test.utils import override_settings

from olympia.amo.tests import TestCase
from olympia.api.throttling import GranularUserRateThrottle


class TestGranularUserRateThrottle(TestCase):
    def setUp(self):
        self.throttle = GranularUserRateThrottle()

    def test_backwards_compatible_format(self):
        # test the original DRF rate string format x/timeperiod works
        assert self.throttle.parse_rate('1/minute') == (1, 60)
        assert self.throttle.parse_rate('24/s') == (24, 1)
        assert self.throttle.parse_rate('456/hour') == (456, 3600)

    def test_granular_format(self):
        assert self.throttle.parse_rate('1/5minute') == (1, 60 * 5)
        assert self.throttle.parse_rate('24/1s') == (24, 1)
        assert self.throttle.parse_rate('456/7hour') == (456, 7 * 3600)

    @mock.patch('rest_framework.throttling.UserRateThrottle.allow_request')
    def test_allow_request_if_api_throttling_setting_is_false(
            self, allow_request_mock):
        request = RequestFactory().get('/test')
        view = object()

        # Pretend the parent class would always throttle requests if called.
        allow_request_mock.return_value = False

        # With the setting set to True (the default), throttle as normal.
        assert settings.API_THROTTLING is True
        assert self.throttle.allow_request(request, view) is False
        assert allow_request_mock.call_count == 1

        # With the setting set to False, ignore throttling.
        with override_settings(API_THROTTLING=False):
            assert settings.API_THROTTLING is False
            assert self.throttle.allow_request(request, view) is True
            # The parent class hasn't been called an additional time.
            assert allow_request_mock.call_count == 1

        # And again set to True to be sure.
        assert settings.API_THROTTLING is True
        assert self.throttle.allow_request(request, view) is False
        assert allow_request_mock.call_count == 2
