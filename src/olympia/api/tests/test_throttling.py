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
