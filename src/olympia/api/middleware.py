import re

from django.conf import settings
from django.middleware.gzip import GZipMiddleware
from django.utils.deprecation import MiddlewareMixin


class IdentifyAPIRequestMiddleware(MiddlewareMixin):
    def identify_request(self, request):
        request.is_api = re.match(settings.DRF_API_REGEX, request.path_info)

    def process_request(self, request):
        self.identify_request(request)

    def process_exception(self, request, exception):
        self.identify_request(request)


class GZipMiddlewareForAPIOnly(GZipMiddleware):
    """
    Wrapper around GZipMiddleware, which only enables gzip for API responses.
    It specifically avoids enabling it for non-API responses because that might
    leak security tokens through the BREACH attack.

    https://www.djangoproject.com/weblog/2013/aug/06/breach-and-django/
    http://breachattack.com/
    https://bugzilla.mozilla.org/show_bug.cgi?id=960752
    """

    def process_response(self, request, response):
        if not request.is_api:
            return response

        return super(GZipMiddlewareForAPIOnly, self).process_response(
            request, response)
