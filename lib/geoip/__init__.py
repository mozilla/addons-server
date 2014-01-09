import logging

import requests
import waffle
from django_statsd.clients import statsd

from mkt import regions

log = logging.getLogger('z.geoip')


def is_public(ip):
    parts = map(int, ip.split('.'))
    # localhost
    if ip == '127.0.0.1':
        return False
    # 10.x.x.x
    elif parts[0] == 10:
        return False
    # 192.168.x.x
    elif parts[0] == 192 and parts[1] == 168:
        return False
    # 172.16-32.x.x
    elif parts[0] == 172 and 16 <= parts[1] <= 31:
        return False
    return True


class GeoIP:
    """Call to geodude server to resolve an IP to Geo Info block."""

    def __init__(self, settings):
        self.timeout = float(getattr(settings, 'GEOIP_DEFAULT_TIMEOUT', .2))
        self.url = getattr(settings, 'GEOIP_URL', '')
        self.default_val = getattr(settings, 'GEOIP_DEFAULT_VAL',
                                   regions.RESTOFWORLD.slug).lower()

    def lookup(self, address):
        """Resolve an IP address to a block of geo information.

        If a given address is unresolvable or the geoip server is not defined,
        return the default as defined by the settings, or "restofworld".

        """
        if (self.url and waffle.switch_is_active('geoip-geodude') and
            is_public(address)):
            with statsd.timer('z.geoip'):
                res = None
                try:
                    res = requests.post('{0}/country.json'.format(self.url),
                                        timeout=self.timeout,
                                        data={'ip': address})
                except requests.Timeout:
                    statsd.incr('z.geoip.timeout')
                    log.error(('Geodude timed out looking up: {0}'
                               .format(address)))
                except requests.RequestException as e:
                    statsd.incr('z.geoip.error')
                    log.error('Geodude connection error: {0}'.format(str(e)))
                if res and res.status_code == 200:
                    statsd.incr('z.geoip.success')
                    return res.json().get('country_code',
                                          self.default_val).lower()
        return self.default_val
