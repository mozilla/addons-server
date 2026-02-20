import os
from unittest.mock import Mock, PropertyMock, patch

from django import test
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, HttpResponseRedirect
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.accounts.utils import fxa_login_url, path_with_query
from olympia.accounts.verify import IdentificationError
from olympia.amo.middleware import (
    AuthenticationMiddlewareWithoutAPI,
    CacheControlMiddleware,
    GraphiteMiddlewareNoAuth,
    RequestIdMiddleware,
    SetRemoteAddrFromForwardedFor,
    TokenValidMiddleware,
)
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, user_factory
from olympia.zadmin.models import Config


class TestMiddleware(TestCase):
    def test_no_vary_cookie(self):
        addon_factory(slug='foo')
        # Requesting / forces a Vary on Accept-Language on User-Agent, since
        # we redirect to /<lang>/<app>/.
        response = test.Client().get('/addon/foo/statistics/')
        assert response['Vary'] == 'Accept-Language, User-Agent'

        # Only Vary on Accept-Encoding after that (because of gzip middleware).
        # Crucially, we avoid Varying on Cookie.
        response = test.Client().get('/addon/foo/statistics/', follow=True)
        assert response['Vary'] == 'Accept-Encoding'

    @patch('django.contrib.auth.middleware.AuthenticationMiddleware.process_request')
    def test_authentication_used_outside_the_api(self, process_request):
        req = RequestFactory().get('/')
        req.is_api = False
        AuthenticationMiddlewareWithoutAPI(lambda: None).process_request(req)
        assert process_request.called

    @patch('django.contrib.sessions.middleware.SessionMiddleware.process_request')
    def test_authentication_not_used_with_the_api(self, process_request):
        req = RequestFactory().get('/')
        req.is_api = True
        AuthenticationMiddlewareWithoutAPI(lambda: None).process_request(req)
        assert not process_request.called

    @patch('django.contrib.auth.middleware.AuthenticationMiddleware.process_request')
    def test_authentication_is_used_with_accounts_auth(self, process_request):
        req = RequestFactory().get('/api/v3/accounts/authenticate/')
        req.is_api = True
        AuthenticationMiddlewareWithoutAPI(lambda: None).process_request(req)
        assert process_request.call_count == 1

        req = RequestFactory().get('/api/v4/accounts/authenticate/')
        req.is_api = True
        AuthenticationMiddlewareWithoutAPI(lambda: None).process_request(req)
        assert process_request.call_count == 2

        req = RequestFactory().get('/api/v5/accounts/authenticate/')
        req.is_api = True
        AuthenticationMiddlewareWithoutAPI(lambda: None).process_request(req)
        assert process_request.call_count == 3

    def test_lbheartbeat_middleware(self):
        # /__lbheartbeat__ should be return a 200 from middleware, bypassing later
        # middleware and view code.

        with self.assertNumQueries(0):
            response = test.Client().get('/__lbheartbeat__', SERVER_NAME='elb-internal')
        assert response.status_code == 200
        assert response.content == b''
        assert response['Cache-Control'] == (
            'max-age=0, no-cache, no-store, must-revalidate, private'
        )


def test_redirect_with_unicode_get():
    response = test.Client().get(
        '/da/firefox/addon/5457?from=/da/firefox/'
        'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
        '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
        'E3%82%BA'
    )
    assert response.status_code == 302
    assert 'utm_term=Google+%E3%83%90%E3%82%BA' in response['Location']


def test_source_with_wrong_unicode_get():
    # The following url is a string (bytes), not unicode.
    response = test.Client().get(
        '/firefox/collections/mozmj/autumn/?source=firefoxsocialmedia\x14\x85'
    )
    assert response.status_code == 302
    assert response['Location'].endswith('?source=firefoxsocialmedia%14%C3%82%C2%85')


@patch('olympia.zadmin.models.get_config', lambda s: None)
def test_trailing_slash_middleware():
    response = test.Client().get('/en-US/review_guide/?xxx=\xc3')
    assert response.status_code == 301
    assert response['Location'].endswith('/en-US/review_guide?xxx=%C3%83%C2%83')


class AdminMessageTest(TestCase):
    def test_message(self):
        config = Config.objects.create(key='site_notice', value='ET Sighted.')

        response = self.client.get(reverse('devhub.index'), follow=True)
        doc = pq(response.content)
        assert doc('#site-notice').text() == 'ET Sighted.'

        config.delete()

        response = self.client.get(reverse('devhub.index'), follow=True)
        doc = pq(response.content)
        assert len(doc('#site-notice')) == 0


class TestNoDjangoDebugToolbar(TestCase):
    """Make sure the Django Debug Toolbar isn't available when DEBUG=False."""

    def test_no_django_debug_toolbar(self):
        with self.settings(DEBUG=False):
            res = self.client.get(reverse('devhub.index'), follow=True)
            assert b'djDebug' not in res.content
            assert b'debug_toolbar' not in res.content


def test_request_id_middleware(client):
    """Test that we add a request id to every response"""
    response = client.get(reverse('version.json'))
    assert response.status_code == 200
    assert isinstance(response['X-AMO-Request-ID'], str)

    # Test that we set `request.request_id` too

    request = RequestFactory().get('/')
    RequestIdMiddleware(lambda: None).process_request(request)
    assert request.request_id


class TestSetRemoteAddrFromForwardedFor(TestCase):
    def setUp(self):
        self.middleware = SetRemoteAddrFromForwardedFor(lambda: None)

    def test_no_special_headers(self):
        request = RequestFactory().get('/', REMOTE_ADDR='4.8.15.16')
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

    def test_request_not_from_cdn(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='4.8.15.16', HTTP_X_FORWARDED_FOR='2.3.4.2,4.8.15.16'
        )
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

    @patch.dict(os.environ, {'DEPLOY_PLATFORM': 'gcp'})
    def test_request_not_from_cdn_on_gcp(self):
        request = RequestFactory().get(
            '/', REMOTE_ADDR='2.3.4.2', HTTP_X_FORWARDED_FOR='4.8.15.16,2.3.4.2'
        )
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

        request = RequestFactory().get(
            '/', REMOTE_ADDR='2.3.4.2', HTTP_X_FORWARDED_FOR='1.1.1.1,4.8.15.16,2.3.4.2'
        )
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

    @override_settings(SECRET_CDN_TOKEN=None)
    def test_request_not_from_cdn_because_setting_is_none(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='4.8.15.16',
            HTTP_X_FORWARDED_FOR='2.3.4.2,4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN=None,
        )
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

    @override_settings(SECRET_CDN_TOKEN='foo')
    def test_request_not_from_cdn_because_header_secret_is_invalid(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='4.8.15.16',
            HTTP_X_FORWARDED_FOR='2.3.4.2,4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='not-foo',
        )
        assert not self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '4.8.15.16'

    @override_settings(SECRET_CDN_TOKEN='foo')
    def test_request_from_cdn_but_only_one_ip_in_x_forwarded_for(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='4.8.15.16',
            HTTP_X_FORWARDED_FOR='4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
        )
        assert self.middleware.is_request_from_cdn(request)
        with self.assertRaises(ImproperlyConfigured):
            self.middleware.process_request(request)

    @override_settings(SECRET_CDN_TOKEN='foo')
    def test_request_from_cdn_but_empty_values_in_x_forwarded_for(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='4.8.15.16',
            HTTP_X_FORWARDED_FOR=',',
            HTTP_X_REQUEST_VIA_CDN='foo',
        )
        assert self.middleware.is_request_from_cdn(request)
        with self.assertRaises(ImproperlyConfigured):
            self.middleware.process_request(request)

    @override_settings(SECRET_CDN_TOKEN='foo')
    def test_request_from_cdn_pick_second_to_last_ip_in_x_forwarded_for(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='4.8.15.16',
            HTTP_X_FORWARDED_FOR=',, 2.3.4.2,  4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
        )
        assert self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '2.3.4.2'

    @override_settings(SECRET_CDN_TOKEN='foo')
    @patch.dict(os.environ, {'DEPLOY_PLATFORM': 'gcp'})
    def test_request_from_cdn_pick_third_to_last_ip_in_x_forwarded_for_on_gcp(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='1.1.1.1',
            HTTP_X_FORWARDED_FOR=',, 2.3.4.2, 1.1.1.1, 4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
        )
        assert self.middleware.is_request_from_cdn(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '2.3.4.2'

    @override_settings(SECRET_CDN_TOKEN='foo')
    @patch.dict(os.environ, {'DEPLOY_PLATFORM': 'gcp'})
    def test_request_from_cdn_with_shield(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='1.1.1.1',
            HTTP_X_FORWARDED_FOR='7.7.7.7, 2.3.4.2, 2.2.2.2, 1.1.1.1, 4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
            headers={'X-AMO-Request-Shielded': 'true'},
        )
        assert self.middleware.is_request_shielded(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '2.3.4.2'

    @override_settings(SECRET_CDN_TOKEN='foo')
    @patch.dict(os.environ, {'DEPLOY_PLATFORM': 'gcp'})
    def test_request_from_cdn_without_shield(self):
        # Shield header can be explicitly set to "false" instead of "true", we
        # just ignore it in that case.
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='1.1.1.1',
            HTTP_X_FORWARDED_FOR='7.7.7.7, 2.3.4.2, 1.1.1.1, 4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
            headers={'X-AMO-Request-Shielded': 'false'},
        )
        assert not self.middleware.is_request_shielded(request)
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '2.3.4.2'

    @patch.dict(os.environ, {'DEPLOY_PLATFORM': 'gcp'})
    def test_request_not_from_cdn_should_ignore_shield_header(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='1.1.1.1',
            HTTP_X_FORWARDED_FOR='7.7.7.7, 2.3.4.2, 4.8.15.16',
            HTTP_X_REQUEST_VIA_CDN='foo',
        )
        self.middleware.process_request(request)
        assert request.META['REMOTE_ADDR'] == '2.3.4.2'


class TestCacheControlMiddleware(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_not_api_should_not_cache(self):
        request = self.request_factory.get('/bar')
        request.is_api = False
        response = HttpResponse()
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 's-maxage=0'

    def test_authenticated_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        request.META = {'HTTP_AUTHORIZATION': 'foo'}
        response = HttpResponse()
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 's-maxage=0'

    def test_non_read_only_http_method_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        for method in ('POST', 'DELETE', 'PUT', 'PATCH'):
            request.method = method
            response = CacheControlMiddleware(lambda x: HttpResponse())(request)
            assert response['Cache-Control'] == 's-maxage=0'

    def test_disable_caching_arg_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        request.GET = {'disable_caching': '1'}
        response = HttpResponse()
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 's-maxage=0'

    def test_cookies_in_response_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        response.set_cookie('foo', 'bar')
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 's-maxage=0'

    def test_cache_control_already_set_should_not_override(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        response['Cache-Control'] = 'max-age=3600'
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 'max-age=3600'

    def test_cache_control_already_set_to_0_should_not_set_s_maxage(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        response = HttpResponse()
        response['Cache-Control'] = 'max-age=0'
        response = CacheControlMiddleware(lambda x: response)(request)
        assert response['Cache-Control'] == 'max-age=0'

    def test_non_success_status_code_should_not_cache(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        for status_code in (400, 401, 403, 404, 429, 500, 502, 503, 504):
            response = CacheControlMiddleware(
                lambda x, status=status_code: HttpResponse(status=status)
            )(request)
            assert response['Cache-Control'] == 's-maxage=0'

    def test_everything_ok_should_cache_for_3_minutes(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        for status_code in (200, 201, 202, 204, 301, 302, 303, 304):
            response = CacheControlMiddleware(
                lambda x, status=status_code: HttpResponse(status=status)
            )(request)
            assert response['Cache-Control'] == 'max-age=360'

    def test_services_amo_should_cache_for_one_hour(self):
        request = self.request_factory.get('/api/v5/foo')
        request.is_api = True
        request.META['SERVER_NAME'] = settings.SERVICES_DOMAIN
        for status_code in (200, 201, 202, 204, 301, 302, 303, 304):
            response = CacheControlMiddleware(
                lambda x, status=status_code: HttpResponse(status=status)
            )(request)
            assert response['Cache-Control'] == 'max-age=3600'

    def test_functional_should_cache(self):
        response = self.client.get(reverse_ns('amo-site-status'))
        assert response.status_code == 200
        assert 'Cache-Control' in response
        assert response['Cache-Control'] == 'max-age=360'

    def test_functional_should_not_cache(self):
        response = self.client.get(
            reverse_ns('amo-site-status'), HTTP_AUTHORIZATION='blah'
        )
        assert response.status_code == 200
        assert response['Cache-Control'] == 's-maxage=0'


class TestTokenValidMiddleware(TestCase):
    def setUp(self):
        self.get_response_mock = Mock()
        self.response = Mock()
        self.response.data = {}
        self.get_response_mock.return_value = self.response
        self.middleware = TokenValidMiddleware(self.get_response_mock)
        self.update_token_mock = self.patch(
            'olympia.amo.middleware.check_and_update_fxa_access_token'
        )
        self.user = user_factory()

    def get_request(self, session=None):
        request = RequestFactory().get('/')
        request.user = self.user
        request.session = {SESSION_KEY: str(self.user.id), **(session or {})}
        return request

    def test_check_token_returns(self):
        request = self.get_request(session={'access_token_expiry': 12345})
        assert self.middleware(request) == self.response
        self.update_token_mock.assert_called_with(request)

    def test_redirect_because_check_token_raises(self):
        self.update_token_mock.side_effect = IdentificationError()
        request = self.get_request()
        response = self.middleware(request)
        assert isinstance(response, HttpResponseRedirect)
        assert response['Location'] == fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=request.session['fxa_state'],
            next_path=path_with_query(request),
        )

    def test_anonymous_user(self):
        request = RequestFactory().get('/')
        request.session = {}
        assert self.middleware(request) == self.response
        self.update_token_mock.assert_not_called()


@patch('olympia.amo.middleware.statsd')
class TestGraphiteMiddlewareNoAuth(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.response = HttpResponse()

    def test_graphite_response(self, statsd_mock):
        gmw = GraphiteMiddlewareNoAuth(lambda: None)
        gmw.process_response(self.request, self.response)
        assert statsd_mock.incr.call_count == 1
        assert statsd_mock.incr.call_args[0] == ('response.200',)

    def test_graphite_response_authenticated(self, statsd_mock):
        self.request.user = Mock()
        is_authenticated_mock = PropertyMock(return_value=True)
        type(self.request.user).is_authenticated = is_authenticated_mock
        gmw = GraphiteMiddlewareNoAuth(lambda: None)
        gmw.process_response(self.request, self.response)
        assert is_authenticated_mock.call_count == 0
        assert statsd_mock.incr.call_count == 1
        assert statsd_mock.incr.call_args[0] == ('response.200',)

    def test_graphite_exception(self, statsd_mock):
        gmw = GraphiteMiddlewareNoAuth(lambda: None)
        gmw.process_exception(self.request, None)
        assert statsd_mock.incr.call_count == 1
        assert statsd_mock.incr.call_args[0] == ('response.500',)

    def test_graphite_exception_authenticated(self, statsd_mock):
        self.request.user = Mock()
        is_authenticated_mock = PropertyMock(return_value=True)
        type(self.request.user).is_authenticated = is_authenticated_mock
        gmw = GraphiteMiddlewareNoAuth(lambda: None)
        gmw.process_exception(self.request, None)
        assert is_authenticated_mock.call_count == 0
        assert statsd_mock.incr.call_count == 1
        assert statsd_mock.incr.call_args[0] == ('response.500',)

    @override_settings(ENV='dev')
    def test_functional_middleware_used(self, statsd_mock):
        self.client.force_login(user_factory())
        with self.assertNumQueries(0):
            response = self.client.get(reverse_ns('amo.client_info'))
        assert response.status_code == 200
        assert statsd_mock.incr.call_count == 1
        assert statsd_mock.incr.call_args[0] == ('response.200',)
