import re

from django.conf import settings
from django.utils.cache import get_max_age, patch_cache_control, patch_vary_headers
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


class APICacheControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        request_conditions = (
            request.is_api
            and request.method in ('GET', 'HEAD')
            and 'HTTP_AUTHORIZATION' not in request.META
            and 'disable_caching' not in request.GET
        )
        response_conditions = (
            not response.cookies
            and response.status_code >= 200
            and response.status_code < 400
            and get_max_age(response) is None
        )
        if request_conditions and response_conditions:
            patch_cache_control(response, max_age=settings.API_CACHE_DURATION)
        return response
