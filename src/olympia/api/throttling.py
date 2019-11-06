import re
import time

from django.conf import settings

from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle


# Note: all classes defined in this module should obey API_THROTTLING and
# deactivate throttling when this setting is False. This allows us to
# deactivate throttling on dev easily.


class GranularUserRateThrottle(UserRateThrottle):
    """
    Throttling class that works like DRF's UserRateThrottle but supports
    granular rates like 1/5second, and can be deactivated through a
    API_THROTTLING django setting.

    Its scope defaults to `user` but in most cases we'll want the child class
    to override that and add a custom rate.
    """

    RATE_REGEX = r'(?P<num>\d+)\/(?P<period_num>\d{0,2})(?P<period>\w)'
    timer = time.time

    def __init__(self):
        super().__init__()
        # Re-initialize timer at __init__() to allow freeze_gun.freeze_time()
        # to work properly in tests.
        self.timer = time.time

    def allow_request(self, request, view):
        if settings.API_THROTTLING:
            return super(GranularUserRateThrottle, self).allow_request(request, view)
        else:
            return True

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num, period_num, period = re.match(self.RATE_REGEX, rate).groups()
        num_requests = int(num)
        multipler = int(period_num) if period_num else 1
        duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[period] * multipler
        return (num_requests, duration)


class GranularIPRateThrottle(GranularUserRateThrottle):
    """
    Throttling class that works like DRF's AnonRateThrottle but is always
    applied, even to authenticated requests, supports granular rates like
    1/5second, and can be deactivated through a API_THROTTLING django setting.

    Its scope defaults to `anon` to follow DRF's default behaviour regarding
    IP throttling but in most cases we'll want the child class to override that
    and add a custom rate.
    """

    scope = 'anon'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),  # This will get the IP.
        }


class ThrottleOnlyUnsafeMethodsMixin:
    """Mixin to add to a throttling class to only apply the throttling if the
    request method is "unsafe", i.e. POST/PUT/PATCH/DELETE."""

    def allow_request(self, request, view):
        if request.method not in SAFE_METHODS:
            return super().allow_request(request, view)
        else:
            return True
