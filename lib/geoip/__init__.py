import logging

import requests
import waffle
from django_statsd.clients import statsd

from mkt import regions

log = logging.getLogger('z.geoip')

class GeoIP:
    """Call to geodude server to resolve an IP to Geo Info block."""

    def __init__(self, settings):
        self.timeout = float(getattr(settings, 'GEOIP_DEFAULT_TIMEOUT', .2))
        self.url = getattr(settings, 'GEOIP_URL', '')
        self.default_val = getattr(settings, 'GEOIP_DEFAULT_VAL',
                                   regions.WORLDWIDE.slug).lower()

    def lookup(self, address):
        """Resolve an IP address to a block of geo information.

        If a given address is unresolvable or the geoip server is not defined,
        return the default as defined by the settings, or "worldwide".

        """
        if self.url and waffle.switch_is_active('geoip-geodude'):
            with statsd.timer('z.geoip'):
                try:
                    res = requests.post('{0}/country.json'.format(self.url),
                                        timeout=self.timeout,
                                        data={'ip': address})
                except requests.Timeout:
                    log.error(('Geodude timed out looking up: {0}'
                               .format(address)))
                except requests.RequestException as e:
                    log.error('Geodude connection error: {0}'.format(str(e)))
                if res.status_code == 200:
                    return res.json.get('country_code',
                                        self.default_val).lower()
        return self.default_val
