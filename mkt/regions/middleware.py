from django.conf import settings

import commonware.log
from django_statsd.clients import statsd

from lib.geoip import GeoIP

import mkt

log = commonware.log.getLogger('mkt.regions')


class RegionMiddleware(object):
    """Figure out the user's region and set request.REGION accordingly, storing
    it on the request.amo_user if there is one."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def region_from_request(self, request):
        address = request.META.get('REMOTE_ADDR')
        ip_reg = self.geoip.lookup(address)
        log.info('Geodude lookup for {0} returned {1}'
                 .format(address, ip_reg))
        return mkt.regions.REGIONS_DICT.get(ip_reg, mkt.regions.RESTOFWORLD)

    def process_request(self, request):
        regions = mkt.regions.REGION_LOOKUP

        user_region = restofworld = mkt.regions.RESTOFWORLD

        if not getattr(request, 'API', False):
            request.REGION = restofworld
            mkt.regions.set_region(restofworld)
            return

        # Try 'region' in POST/GET data first, if it's not there try geoip.
        url_region = request.REQUEST.get('region')
        if url_region in regions:
            statsd.incr('z.regions.middleware.source.url')
            user_region = regions[url_region]
            log.info('Region {0} specified in URL; region set as {1}'
                     .format(url_region, user_region.slug))
        else:
            statsd.incr('z.regions.middleware.source.geoip')
            user_region = self.region_from_request(request)
            log.info('Region not specified in URL; region set as {0}'
                     .format(user_region.slug))

        # Update the region on the user object if it changed.
        amo_user = getattr(request, 'amo_user', None)
        if amo_user and amo_user.region != user_region.slug:
            amo_user.region = user_region.slug
            amo_user.save()

        # Persist the region on the request / local thread.
        request.REGION = user_region
        mkt.regions.set_region(user_region)
