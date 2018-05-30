import re

from rest_framework.throttling import UserRateThrottle


class GranularUserRateThrottle(UserRateThrottle):
    RATE_REGEX = r'(?P<num>\d+)\/(?P<period_num>\d{0,2})(?P<period>\w)'

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num, period_num, period = re.match(self.RATE_REGEX, rate).groups()
        num_requests = int(num)
        multipler = int(period_num) if period_num else 1
        duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[period] * multipler
        return (num_requests, duration)
