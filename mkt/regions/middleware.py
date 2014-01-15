from django.conf import settings

from django_statsd.clients import statsd

from lib.geoip import GeoIP

import mkt


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def region_from_request(self, request):
        ip_reg = self.geoip.lookup(request.META.get('REMOTE_ADDR'))
        if ip_reg in mkt.regions.REGIONS_DICT:
            return ip_reg
        else:
            return mkt.regions.RESTOFWORLD.slug

    def process_request(self, request):
        regions = mkt.regions.REGION_LOOKUP

        reg = restofworld = mkt.regions.RESTOFWORLD.slug
        stored_reg = ''

        if not getattr(request, 'API', False):
            request.REGION = regions[restofworld]
            mkt.regions.set_region(restofworld)
            return

        # ?region= -> geoip -> lang
        url_region = request.REQUEST.get('region')
        if url_region in regions:
            statsd.incr('z.regions.middleware.source.url')
            reg = url_region
        else:
            reg = self.region_from_request(request)
            # If the above fails, let's try `Accept-Language`.
            if reg == restofworld:
                statsd.incr('z.regions.middleware.source.accept-lang')
                if request.LANG == settings.LANGUAGE_CODE:
                    choices = mkt.regions.REGIONS_CHOICES[1:]
                else:
                    choices = mkt.regions.REGIONS_CHOICES
                if request.LANG:
                    for name, region in choices:
                        if name.lower() in request.LANG.lower():
                            reg = region.slug
                            break
                # All else failed, try to match against our forced Language.
                if reg == mkt.regions.RESTOFWORLD.slug:
                    # Try to find a suitable region.
                    for name, region in choices:
                        if region.default_language == request.LANG:
                            reg = region.slug
                            break

                a_l = request.META.get('HTTP_ACCEPT_LANGUAGE')
                if (reg == 'us' and a_l is not None
                    and not a_l.startswith('en')):
                    # Let us default to restofworld if it's not English.
                    reg = mkt.regions.RESTOFWORLD.slug
            else:
                statsd.incr('z.regions.middleware.source.geoip')

        # Update cookie if value have changed.
        if reg != stored_reg:
            if (getattr(request, 'amo_user', None)
                and request.amo_user.region != reg):
                request.amo_user.region = reg
                request.amo_user.save()

        request.REGION = regions[reg]
        mkt.regions.set_region(reg)
