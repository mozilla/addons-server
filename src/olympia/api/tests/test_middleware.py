from django.http import HttpResponse
from django.test.client import RequestFactory

from olympia.amo.tests import reverse_ns, TestCase
from olympia.api.middleware import APICacheControlMiddleware, APIRequestMiddleware


class TestAPIRequestMiddleware(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_api_identified(self):
        request = self.request_factory.get('/api/v3/lol/')
        APIRequestMiddleware().process_request(request)
        assert request.is_api

    def test_vary_applied(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'X-Country-Code, Accept-Language'

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'Foo, Bar, X-Country-Code, Accept-Language'

    def test_vary_not_applied_outside_api(self):
        request = self.request_factory.get('/somewhere')
        request.is_api = False
        response = HttpResponse()
        APIRequestMiddleware().process_response(request, response)
        assert not response.has_header('Vary')

        response['Vary'] = 'Foo, Bar'
        APIRequestMiddleware().process_response(request, response)
        assert response['Vary'] == 'Foo, Bar'

    def test_disabled_for_the_rest(self):
        """Test that we don't tag the request as API on "regular" pages."""
        request = self.request_factory.get('/overtherainbow')
        APIRequestMiddleware().process_request(request)
        assert not request.is_api

        request = self.request_factory.get('/overtherainbow')
        APIRequestMiddleware().process_request(request)
        assert not request.is_api


class TestAPICacheControlMiddleware(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_not_api_should_not_cache(self):
        request = self.request_factory.get('/bar')
        request.is_api = False
        response = HttpResponse()
        response = APICacheControlMiddleware(lambda x: response)(request)
        assert 'Cache-Control' not in response

    def test_authenticated_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        request.META = {'HTTP_AUTHORIZATION': 'foo'}
        response = HttpResponse()
        response = APICacheControlMiddleware(lambda x: response)(request)
        assert 'Cache-Control' not in response

    def test_non_read_only_http_method_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        for method in ('POST', 'DELETE', 'PUT', 'PATCH'):
            request.method = method
            response = HttpResponse()
            response = APICacheControlMiddleware(lambda x: response)(request)
            assert 'Cache-Control' not in response

    def test_disable_caching_arg_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        request.GET = {'disable_caching': '1'}
        response = HttpResponse()
        response = APICacheControlMiddleware(lambda x: response)(request)
        assert 'Cache-Control' not in response

    def test_cookies_in_response_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        response.set_cookie('foo', 'bar')
        response = APICacheControlMiddleware(lambda x: response)(request)
        assert 'Cache-Control' not in response

    def test_cache_control_already_set_should_not_override(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        response['Cache-Control'] = 'max-age=3600'
        response = APICacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 'max-age=3600'

    def test_non_success_status_code_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        for status_code in (400, 401, 403, 404, 429, 500, 502, 503, 504):
            response.status_code = status_code
            response = APICacheControlMiddleware(lambda x: response)(request)
            assert 'Cache-Control' not in response

    def test_everything_ok_should_cache_for_3_minutes(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        for status_code in (200, 201, 202, 204, 301, 302, 303, 304):
            response.status_code = status_code
            response = APICacheControlMiddleware(lambda x: response)(request)
            assert response['Cache-Control'] == 'max-age=180'

    def test_functional_should_cache(self):
        response = self.client.get(reverse_ns('amo-site-status'))
        assert response.status_code == 200
        assert 'Cache-Control' in response
        assert response['Cache-Control'] == 'max-age=180'

    def test_functional_should_not_cache(self):
        response = self.client.get(
            reverse_ns('amo-site-status'), HTTP_AUTHORIZATION='blah'
        )
        assert response.status_code == 200
        assert 'Cache-Control' not in response
