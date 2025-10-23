import re
import time

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle

import olympia
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog


log = olympia.core.logger.getLogger('z.api.throttling')


# Note: for consistency, all classes defined in this module should inherit
# GranularUserRateThrottle - it adds features we want to have across all our
# throttles.


class GranularUserRateThrottle(UserRateThrottle):
    """
    Base throttling class all our throttles should inherit from.

    Works like DRF's UserRateThrottle but supports granular rates like
    1/5second, can be deactivated through a API_THROTTLING django setting, and
    can by bypassed by users with the API_BYPASS_THROTTLING permission.

    Its scope defaults to `user` but in most cases we'll want the child class
    to override that and add a custom rate.

    If the request is throttled, it will create activity log associated with
    the user to help us track users that have tried to go over rate limits.
    """

    RATE_REGEX = r'(?P<num>\d+)\/(?P<period_num>\d{0,2})(?P<period>\w)'
    timer = time.time

    def __init__(self):
        super().__init__()
        # Re-initialize timer at __init__() to allow time_machine.travel()
        # to work properly in tests.
        self.timer = time.time

    def allow_request(self, request, view):
        if settings.API_THROTTLING:
            user = getattr(request, 'user', None)
            if acl.action_allowed_for(user, amo.permissions.API_BYPASS_THROTTLING):
                return True
            request_allowed = super().allow_request(request, view)
            if not request_allowed and user and user.is_authenticated:
                log.info('User %s throttled for scope %s', user, self.scope)
                ActivityLog.objects.create(amo.LOG.THROTTLED, self.scope, user=user)

            return request_allowed
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


class CheckThrottlesFormMixin:
    """
    Mixin to add to a django form to check DRF throttles when running clean().

    Requires self.request and self.throttle_classes to be set on the form
    instance. self.throttled_error_message can be used to customize the error
    message on throttled requests.
    """

    throttled_error_message = _(
        'You have submitted this form too many times recently. '
        'Please try again after some time.'
    )

    throttle_classes = ()

    def _clean_fields(self):
        # Note: we override _clean_fields() so that throttles can be run before
        # checking fields, on purpose. This allows us to prevent further
        # validation from taking place, mimicking API behavior, and guarding
        # against potential stuffing attacks.
        if not self.is_throttled():
            return super()._clean_fields()

    def is_throttled(self):
        for throttle in [throttle_class() for throttle_class in self.throttle_classes]:
            if not throttle.allow_request(self.request, None):
                self.add_error(None, self.throttled_error_message)
                return True  # Don't check further throttles if one failed.
        return False


class BurstUserAddonSubmissionThrottle(
    ThrottleOnlyUnsafeMethodsMixin, GranularUserRateThrottle
):
    scope = 'burst_user_addon_submission'
    rate = '3/minute'


class HourlyUserAddonSubmissionThrottle(
    ThrottleOnlyUnsafeMethodsMixin, GranularUserRateThrottle
):
    scope = 'hourly_user_addon_submission'
    rate = '10/hour'


class DailyUserAddonSubmissionThrottle(
    ThrottleOnlyUnsafeMethodsMixin, GranularUserRateThrottle
):
    scope = 'daily_user_addon_submission'
    rate = '24/day'


class BurstIPAddonSubmissionThrottle(
    ThrottleOnlyUnsafeMethodsMixin, GranularIPRateThrottle
):
    scope = 'burst_ip_addon_submission'
    rate = '6/minute'


class HourlyIPAddonSubmissionThrottle(
    ThrottleOnlyUnsafeMethodsMixin, GranularIPRateThrottle
):
    scope = 'hourly_ip_addon_submission'
    rate = '50/hour'


addon_submission_throttles = (
    BurstUserAddonSubmissionThrottle,
    HourlyUserAddonSubmissionThrottle,
    DailyUserAddonSubmissionThrottle,
    BurstIPAddonSubmissionThrottle,
    HourlyIPAddonSubmissionThrottle,
)


class BurstUserFileUploadThrottle(BurstUserAddonSubmissionThrottle):
    scope = 'burst_user_file_upload'
    rate = '6/minute'


class HourlyUserFileUploadThrottle(HourlyUserAddonSubmissionThrottle):
    scope = 'hourly_user_file_upload'
    rate = '20/hour'


class DailyUserFileUploadThrottle(DailyUserAddonSubmissionThrottle):
    scope = 'daily_user_file_upload'
    rate = '48/day'


class BurstIPFileUploadThrottle(BurstIPAddonSubmissionThrottle):
    scope = 'burst_ip_file_upload'
    rate = '6/minute'


class HourlyIPFileUploadThrottle(HourlyIPAddonSubmissionThrottle):
    scope = 'hourly_ip_file_upload'
    rate = '50/hour'


file_upload_throttles = (
    BurstUserFileUploadThrottle,
    HourlyUserFileUploadThrottle,
    DailyUserFileUploadThrottle,
    BurstIPFileUploadThrottle,
    HourlyIPFileUploadThrottle,
)
