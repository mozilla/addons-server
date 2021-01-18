import re

from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin


class APIRequestMiddleware(MiddlewareMixin):
    def identify_request(self, request):
        request.is_api = re.match(settings.DRF_API_REGEX, request.path_info)

    def process_request(self, request):
        self.identify_request(request)

    def process_response(self, request, response):
        if request.is_api:
            patch_vary_headers(response, ['X-Country-Code', 'Accept-Language'])
        return response

    def process_exception(self, request, exception):
        self.identify_request(request)
