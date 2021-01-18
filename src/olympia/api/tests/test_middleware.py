from unittest import mock

from django.http import HttpResponse

from olympia.amo.tests import TestCase
from olympia.api.middleware import APIRequestMiddleware


class TestAPIRequestMiddleware(TestCase):
    def test_api_identified(self):
        request = mock.Mock()
        request.path_info = '/api/v3/lol/'
        APIRequestMiddleware().process_request(request)
        assert request.is_api

    def test_vary_applied(self):
        request = mock.Mock()
        request.is_api = True
        response = HttpResponse()
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'X-Country-Code, Accept-Language'

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'Foo, Bar, X-Country-Code, Accept-Language'

    def test_vary_not_applied_outside_api(self):
        request = mock.Mock()
        request.is_api = False
        response = HttpResponse()
        APIRequestMiddleware().process_response(request, response)
        assert not response.has_header('Vary')

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'Foo, Bar'

    def test_disabled_for_the_rest(self):
        """Test that we don't tag the request as API on "regular" pages."""
        request = mock.Mock()
        request.path_info = '/'
        APIRequestMiddleware().process_request(request)
        assert not request.is_api

        request.path = '/en-US/firefox/'
        APIRequestMiddleware().process_request(request)
        assert not request.is_api
