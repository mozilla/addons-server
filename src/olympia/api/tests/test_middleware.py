from django.http import HttpResponse
from django.test.client import RequestFactory

from olympia.amo.tests import TestCase
from olympia.api.middleware import APIRequestMiddleware


class TestAPIRequestMiddleware(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_api_identified(self):
        request = self.request_factory.get('/api/v3/lol/')
        APIRequestMiddleware(lambda: None).process_request(request)
        assert request.is_api

    def test_vary_applied(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        APIRequestMiddleware(lambda: None).process_response(request, response)
        assert response['Vary'] == 'X-Country-Code, Accept-Language'

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware(lambda: None).process_response(request, response)
        assert response['Vary'] == 'Foo, Bar, X-Country-Code, Accept-Language'

    def test_vary_not_applied_outside_api(self):
        request = self.request_factory.get('/somewhere')
        request.is_api = False
        response = HttpResponse()
        APIRequestMiddleware(lambda: None).process_response(request, response)
        assert not response.has_header('Vary')

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware(lambda: None).process_response(request, response)
        assert response['Vary'] == 'Foo, Bar'

    def test_disabled_for_the_rest(self):
        """Test that we don't tag the request as API on "regular" pages."""
        request = self.request_factory.get('/overtherainbow')
        APIRequestMiddleware(lambda: None).process_request(request)
        assert not request.is_api

        request = self.request_factory.get('/overtherainbow')
        APIRequestMiddleware(lambda: None).process_request(request)
        assert not request.is_api
