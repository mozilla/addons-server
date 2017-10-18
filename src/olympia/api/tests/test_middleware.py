import mock

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.api.middleware import GZipMiddlewareForAPIOnly


class TestGzipMiddleware(TestCase):
    @mock.patch('django.middleware.gzip.GZipMiddleware.process_response')
    def test_enabled_for_api(self, django_gzip_middleware):
        request = mock.Mock()
        request.path = '/api/v3/lol/'
        GZipMiddlewareForAPIOnly().process_response(request, mock.Mock())
        assert django_gzip_middleware.call_count == 1

    @mock.patch('django.middleware.gzip.GZipMiddleware.process_response')
    def test_disabled_for_the_rest(self, django_gzip_middleware):
        request = mock.Mock()
        request.path = '/'
        GZipMiddlewareForAPIOnly().process_response(request, mock.Mock())
        assert django_gzip_middleware.call_count == 0

        request.path = '/en-US/firefox/'
        GZipMiddlewareForAPIOnly().process_response(request, mock.Mock())
        assert django_gzip_middleware.call_count == 0

    def test_settings(self):
        # Gzip middleware should be near the top of the list, so that it runs
        # last in the process_response phase, in case the response body has
        # been modified by another middleware.
        # Sadly, raven inserts 2 middlewares before, but luckily the ones it
        # automatically inserts not modify the response.
        assert (
            settings.MIDDLEWARE_CLASSES[2] ==
            'olympia.api.middleware.GZipMiddlewareForAPIOnly')
