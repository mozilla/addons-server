from unittest import mock

from django.conf import settings
from django.test.client import RequestFactory
from django.test.utils import override_settings

from freezegun import freeze_time
from rest_framework.test import APIRequestFactory, force_authenticate

from olympia.amo.tests import TestCase
from olympia.api.throttling import GranularIPRateThrottle, GranularUserRateThrottle
from olympia.users.models import UserProfile


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
    def test_allow_request_if_api_throttling_setting_is_false(self, allow_request_mock):
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

    def test_freeze_time_works_with_throttling(self):
        old_time = self.throttle.timer()
        with freeze_time('2019-04-08 15:16:23.42'):
            self.throttle.timer() == 1554736583.42
        new_time = self.throttle.timer()
        assert new_time != 1554736583.42
        assert old_time != 1554736583.42
        assert old_time != new_time


class TestGranularIPRateThrottle(TestGranularUserRateThrottle):
    def setUp(self):
        self.throttle = GranularIPRateThrottle()

    def test_get_cache_key_returns_even_for_authenticated_users(self):
        # Like DRF's AnonRateThrottleTests.test_authenticated_user_not_affected
        # except that we should get a cache key regardless of whether the user
        # is authenticated or not.
        request = APIRequestFactory().get('/')
        user = UserProfile.objects.create(username='test')
        force_authenticate(request, user)
        request.user = user
        request.META['REMOTE_ADDR'] = '123.45.67.89'
        expected_key = 'throttle_anon_123.45.67.89'
        assert self.throttle.get_cache_key(request, view={}) == expected_key
