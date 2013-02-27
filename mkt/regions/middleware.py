from threading import local

from django.conf import settings
from django.utils.cache import patch_vary_headers

from lib.geoip import GeoIP

import mkt
from mkt.site.middleware import get_accept_language


class RegionMiddleware(object):
    """Figure out the user's region and store it in a cookie."""

    def __init__(self):
        self.geoip = GeoIP(settings)

    def process_request(self, request):
        regions = mkt.regions.REGIONS_DICT

        reg = mkt.regions.WORLDWIDE.slug
        stored_reg = ''

        # If I have a cookie use that region.
        remembered = request.COOKIES.get('region')
        if remembered in regions:
            reg = stored_reg = remembered

        # Re-detect my region only if my *Accept-Language* is different from
        # that of my previous language.

        lang_changed = (get_accept_language(request)
                        not in request.COOKIES.get('lang', '').split(','))
        if not remembered or lang_changed:
            # If our locale is `en-US`, then exclude the Worldwide region.
            if request.LANG == settings.LANGUAGE_CODE:
                choices = mkt.regions.REGIONS_CHOICES[1:]
            else:
                choices = mkt.regions.REGIONS_CHOICES

            # if we faked the user's LANG, and we still don't have a
            # valid region, try from the IP
            if (request.LANG.lower() not in
                request.META.get('HTTP_ACCEPT_LANGUAGE', '').lower()):
                ip_reg = self.geoip.lookup(request.META.get('REMOTE_ADDR'))
                for name, region in choices:
                    if ip_reg == name:
                        reg = region.slug
                        break
            elif request.LANG:
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

        choice = request.REQUEST.get('region')
        if choice in regions:
            reg = choice

        a_l = request.META.get('HTTP_ACCEPT_LANGUAGE')

        if reg == 'us' and a_l is not None and not a_l.startswith('en'):
            # Let us default to worldwide if it's not English.
            reg = mkt.regions.WORLDWIDE.slug

        # Update cookie if value have changed.
        if reg != stored_reg:
            request.set_cookie('region', reg)

        request.REGION = regions[reg]
        local().region = reg

    def process_response(self, request, response):
        patch_vary_headers(response, ['Accept-Language', 'Cookie'])
        return response
