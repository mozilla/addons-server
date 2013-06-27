from django.conf import settings

from lib.geoip import GeoIP

import mkt


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def region_from_request(self, request):
        ip_reg = self.geoip.lookup(request.META.get('REMOTE_ADDR'))
        for name, region in mkt.regions.REGIONS_CHOICES:
            if ip_reg == name:
                return region.slug
        return mkt.regions.WORLDWIDE.slug

    def process_request(self, request):
        regions = mkt.regions.REGIONS_DICT

        reg = worldwide = mkt.regions.WORLDWIDE.slug
        stored_reg = ''

        # ?region= -> cookie -> geoip -> lang
        url_region = request.REQUEST.get('region')
        cookie_region = request.COOKIES.get('region')
        if url_region in regions:
            reg = url_region
        elif cookie_region in regions:
            reg = stored_reg = cookie_region
        else:
            reg = self.region_from_request(request)
            # If the above fails, let's try `Accept-Language`.
            if reg == worldwide:
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
                if reg == mkt.regions.WORLDWIDE.slug:
                    # Try to find a suitable region.
                    for name, region in choices:
                        if region.default_language == request.LANG:
                            reg = region.slug
                            break

                a_l = request.META.get('HTTP_ACCEPT_LANGUAGE')
                if (reg == 'us' and a_l is not None
                    and not a_l.startswith('en')):
                    # Let us default to worldwide if it's not English.
                    reg = mkt.regions.WORLDWIDE.slug

        # Update cookie if value have changed.
        if reg != stored_reg:
            if (getattr(request, 'amo_user', None)
                and request.amo_user.region != reg):
                request.amo_user.region = reg
                request.amo_user.save()

        request.REGION = regions[reg]
        mkt.regions.set_region(reg)
