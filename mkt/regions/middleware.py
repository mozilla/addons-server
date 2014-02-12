from django.conf import settings

import commonware.log
from django_statsd.clients import statsd

from lib.geoip import GeoIP

import mkt

log = commonware.log.getLogger('mkt.regions')


def _save_if_changed(request, user_region):
    """
    Update the region on the user object if it changed.
    """
    amo_user = getattr(request, 'amo_user', None)
    if amo_user and amo_user.region != user_region.slug:
        amo_user.region = user_region.slug
        amo_user.save()


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def region_from_request(self, request):
        address = request.META.get('REMOTE_ADDR')
        log.info('About to ask Geodude to look up IP {0}'.format(address))
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

        # ?region= -> geoip -> lang
        url_region = request.REQUEST.get('region')
        if url_region in regions:
            statsd.incr('z.regions.middleware.source.url')
            user_region = regions[url_region]
            log.info('Region {0} specified in URL; region set as {1}'
                     .format(url_region, user_region.slug))
        else:
            user_region = self.region_from_request(request)
            log.info('Region not specified in URL; region set as {0}'
                     .format(user_region.slug))
            # If the above fails, let's try `Accept-Language`.
            if user_region == restofworld:
                log.info('Region from GeoIP was RESTOFWORLD')
                statsd.incr('z.regions.middleware.source.accept-lang')
                if request.LANG == settings.LANGUAGE_CODE:
                    choices = mkt.regions.REGIONS_CHOICES[1:]
                else:
                    choices = mkt.regions.REGIONS_CHOICES
                if request.LANG:
                    for name, region in choices:
                        if name.lower() in request.LANG.lower():
                            user_region = region
                            _save_if_changed(request, user_region)
                            break
                # All else failed, try to match against our forced Language.
                if user_region == mkt.regions.RESTOFWORLD:
                    # Try to find a suitable region.
                    for name, region in choices:
                        if region.default_language == request.LANG:
                            user_region = region
                            _save_if_changed(request, user_region)
                            break
                log.info('Region set as {0}'.format(user_region.slug))

                accept_language = request.META.get('HTTP_ACCEPT_LANGUAGE')
                if (user_region == mkt.regions.US
                        and accept_language is not None
                        and not accept_language.startswith('en')):
                    # Let us default to restofworld if it's not English.
                    user_region = mkt.regions.RESTOFWORLD
            else:
                statsd.incr('z.regions.middleware.source.geoip')

        _save_if_changed(request, user_region)
        log.info('Region finally set as {0}'.format(user_region.slug))

        request.REGION = user_region
        mkt.regions.set_region(user_region)
