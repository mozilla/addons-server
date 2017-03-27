# -*- coding: utf-8 -*-
import base64
import urlparse
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.core.urlresolvers import resolve, reverse
from django.test import RequestFactory
from django.test.utils import override_settings

import mock
from rest_framework.test import APIRequestFactory, APITestCase
from waffle.models import Switch

from olympia.access.acl import action_allowed_user
from olympia.access.models import Group, GroupUser
from olympia.accounts import verify, views
from olympia.amo.helpers import absolutify, urlparams
from olympia.amo.tests import (
    assert_url_equal, create_switch, user_factory, APITestClient,
    InitializeSessionMixin, PatchMixin, TestCase, WithDynamicEndpoints)
from olympia.api.authentication import WebTokenAuthentication
from olympia.api.tests.utils import APIKeyAuthTestCase
from olympia.users.models import UserProfile

FXA_CONFIG = {
    'oauth_host': 'https://accounts.firefox.com/v1',
    'client_id': 'amodefault',
    'redirect_url': 'https://addons.mozilla.org/fxa-authenticate',
    'scope': 'profile',
}
SKIP_REDIRECT_FXA_CONFIG = {
    'oauth_host': 'https://accounts.firefox.com/v1',
    'client_id': 'amodefault',
    'redirect_url': 'https://addons.mozilla.org/fxa-authenticate',
    'scope': 'profile',
    'skip_register_redirect': True,
}


@override_settings(FXA_CONFIG={
    'default': FXA_CONFIG,
    'internal': FXA_CONFIG,
    'skip': SKIP_REDIRECT_FXA_CONFIG,
})
class BaseAuthenticationView(APITestCase, PatchMixin,
                             InitializeSessionMixin):

    def setUp(self):
        self.url = reverse(self.view_name)
        self.fxa_identify = self.patch(
            'olympia.accounts.views.verify.fxa_identify')


@override_settings(FXA_CONFIG={'current-config': FXA_CONFIG})
class TestLoginStartBaseView(WithDynamicEndpoints, TestCase):

    class LoginStartView(views.LoginStartBaseView):
        DEFAULT_FXA_CONFIG_NAME = 'current-config'

    def setUp(self):
        super(TestLoginStartBaseView, self).setUp()
        self.endpoint(self.LoginStartView, r'^login/start/')
        self.url = '/en-US/firefox/login/start/'
        self.initialize_session({})

    def test_state_is_set(self):
        self.initialize_session({})
        assert 'fxa_state' not in self.client.session
        state = 'somerandomstate'
        with mock.patch('olympia.accounts.views.generate_fxa_state',
                        lambda: state):
            self.client.get(self.url)
        assert 'fxa_state' in self.client.session
        assert self.client.session['fxa_state'] == state

    def test_redirect_url_is_correct(self):
        self.initialize_session({})
        with mock.patch('olympia.accounts.views.generate_fxa_state',
                        lambda: 'arandomstring'):
            response = self.client.get(self.url)
        assert response.status_code == 302
        url = urlparse.urlparse(response['location'])
        redirect = '{scheme}://{netloc}{path}'.format(
            scheme=url.scheme, netloc=url.netloc, path=url.path)
        assert redirect == 'https://accounts.firefox.com/v1/authorization'
        assert urlparse.parse_qs(url.query) == {
            'action': ['signin'],
            'client_id': ['amodefault'],
            'redirect_url': ['https://addons.mozilla.org/fxa-authenticate'],
            'scope': ['profile'],
            'state': ['arandomstring'],
        }

    def test_state_is_not_overriden(self):
        self.initialize_session({'fxa_state': 'thisisthestate'})
        self.client.get(self.url)
        assert self.client.session['fxa_state'] == 'thisisthestate'

    def test_to_is_included_in_redirect_state(self):
        path = '/addons/unlisted-addon/'
        # The =s will be stripped from the URL.
        assert '=' in base64.urlsafe_b64encode(path)
        state = 'somenewstatestring'
        self.initialize_session({})
        with mock.patch('olympia.accounts.views.generate_fxa_state',
                        lambda: state):
            response = self.client.get(self.url, data={'to': path})
        assert self.client.session['fxa_state'] == state
        url = urlparse.urlparse(response['location'])
        query = urlparse.parse_qs(url.query)
        state_parts = query['state'][0].split(':')
        assert len(state_parts) == 2
        assert state_parts[0] == state
        assert '=' not in state_parts[1]
        assert base64.urlsafe_b64decode(state_parts[1] + '====') == path

    def test_to_is_excluded_when_unsafe(self):
        path = 'https://www.google.com'
        self.initialize_session({})
        response = self.client.get(
            '{url}?to={path}'.format(path=path, url=self.url))
        url = urlparse.urlparse(response['location'])
        query = urlparse.parse_qs(url.query)
        assert ':' not in query['state'][0]


def has_cors_headers(response, origin='https://addons-frontend'):
    return (
        response['Access-Control-Allow-Origin'] == origin and
        response['Access-Control-Allow-Credentials'] == 'true')


def update_domains(overrides):
    overrides = overrides.copy()
    overrides['CORS_ORIGIN_WHITELIST'] = ['addons-frontend', 'localhost:3000']
    return overrides


endpoint_overrides = [
    (regex, update_domains(overrides))
    for regex, overrides in settings.CORS_ENDPOINT_OVERRIDES]


@override_settings(
    FXA_CONFIG={'default': FXA_CONFIG},
    CORS_ENDPOINT_OVERRIDES=endpoint_overrides)
class TestLoginView(BaseAuthenticationView):
    client_class = APITestClient
    view_name = 'accounts.login'

    def setUp(self):
        super(TestLoginView, self).setUp()
        self.client.defaults['HTTP_ORIGIN'] = 'https://addons-frontend'
        self.state = 'stateaosidoiajsdaagdsasi'
        self.initialize_session({'fxa_state': self.state})
        self.code = 'codeaosidjoiajsdioasjdoa'
        self.update_user = self.patch(
            'olympia.accounts.views.update_user')

    def options(self, url, origin):
        return self.client_class(HTTP_ORIGIN=origin).options(url)

    def test_correct_config_is_used(self):
        assert views.LoginView.DEFAULT_FXA_CONFIG_NAME == 'default'
        assert views.LoginView.ALLOWED_FXA_CONFIGS == (
            ['default', 'amo', 'local'])

    def test_cors_addons_frontend(self):
        response = self.options(self.url, origin='https://addons-frontend')
        assert has_cors_headers(response, origin='https://addons-frontend')
        assert response.status_code == 200

    def test_cors_localhost(self):
        response = self.options(self.url, origin='http://localhost:3000')
        assert has_cors_headers(response, origin='http://localhost:3000')
        assert response.status_code == 200

    def test_cors_other(self):
        response = self.options(self.url, origin='https://attacker.com')
        assert 'Access-Control-Allow-Origin' not in response
        assert 'Access-Control-Allow-Methods' not in response
        assert 'Access-Control-Allow-Headers' not in response
        assert 'Access-Control-Allow-Credentials' not in response
        assert response.status_code == 200


class TestLoginStartView(TestCase):

    def test_default_config_is_used(self):
        assert views.LoginStartView.DEFAULT_FXA_CONFIG_NAME == 'default'
        assert views.LoginStartView.ALLOWED_FXA_CONFIGS == (
            ['default', 'amo', 'local'])


class TestLoginUser(TestCase):

    def setUp(self):
        self.request = APIRequestFactory().get('/login')
        self.enable_messages(self.request)
        self.user = UserProfile.objects.create(
            email='real@yeahoo.com', fxa_id='9001')
        self.identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        patcher = mock.patch('olympia.accounts.views.login')
        self.login = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.core.get_remote_addr')
        get_remote_addr_mock = patcher.start()
        get_remote_addr_mock.return_value = '8.8.8.8'
        self.addCleanup(patcher.stop)

    def test_user_gets_logged_in(self):
        views.login_user(self.request, self.user, self.identity)
        self.login.assert_called_with(self.request, self.user)

    def test_login_attempt_is_logged(self):
        now = datetime.now()
        self.user.update(last_login_attempt=now)
        views.login_user(self.request, self.user, self.identity)
        self.login.assert_called_with(self.request, self.user)
        assert self.user.last_login_attempt > now
        assert self.user.last_login_ip == '8.8.8.8'

    def test_email_address_can_change(self):
        self.user.update(email='different@yeahoo.com')
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'

    def test_fxa_id_can_be_set(self):
        self.user.update(fxa_id=None)
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'

    def test_auth_id_updated_if_none(self):
        self.user.update(auth_id=None)
        views.login_user(self.request, self.user, self.identity)
        self.user.reload()
        assert self.user.auth_id


class TestFindUser(TestCase):

    def test_user_exists_with_uid(self):
        user = UserProfile.objects.create(fxa_id='9999', email='me@amo.ca')
        found_user = views.find_user({'uid': '9999', 'email': 'you@amo.ca'})
        assert user == found_user

    def test_user_exists_with_email(self):
        user = UserProfile.objects.create(fxa_id='9999', email='me@amo.ca')
        found_user = views.find_user({'uid': '8888', 'email': 'me@amo.ca'})
        assert user == found_user

    def test_user_exists_with_both(self):
        user = UserProfile.objects.create(fxa_id='9999', email='me@amo.ca')
        found_user = views.find_user({'uid': '9999', 'email': 'me@amo.ca'})
        assert user == found_user

    def test_two_users_exist(self):
        UserProfile.objects.create(
            fxa_id='9999', email='me@amo.ca', username='me')
        UserProfile.objects.create(
            fxa_id='8888', email='you@amo.ca', username='you')
        with self.assertRaises(UserProfile.MultipleObjectsReturned):
            views.find_user({'uid': '9999', 'email': 'you@amo.ca'})


class TestRenderErrorHTML(TestCase):

    def make_request(self):
        request = APIRequestFactory().get(reverse('accounts.authenticate'))
        request.user = AnonymousUser()
        return self.enable_messages(request)

    def login_url(self, **params):
        return urlparams(reverse('users.login'), **params)

    def render_error(self, request, error, next_path=None):
        return views.render_error(
            request, error, format='html', next_path=next_path)

    def test_error_no_code_with_safe_path(self):
        request = self.make_request()
        assert len(get_messages(request)) == 0
        response = self.render_error(
            request, views.ERROR_NO_CODE, next_path='/over/here')
        assert response.status_code == 302
        messages = get_messages(request)
        assert len(messages) == 1
        assert 'could not be parsed' in next(iter(messages)).message
        assert_url_equal(response['location'], absolutify('/over/here'))
        response = self.render_error(
            request, views.ERROR_NO_CODE, next_path=None)
        assert response.status_code == 302
        messages = get_messages(request)
        assert len(messages) == 1
        assert 'could not be parsed' in next(iter(messages)).message
        assert_url_equal(response['location'], self.login_url())

    def test_error_no_profile_with_no_path(self):
        request = self.make_request()
        assert len(get_messages(request)) == 0
        response = self.render_error(request, views.ERROR_NO_PROFILE)
        assert response.status_code == 302
        messages = get_messages(request)
        assert len(messages) == 1
        assert ('Firefox Account could not be found'
                in next(iter(messages)).message)
        assert_url_equal(response['location'], self.login_url())

    def test_error_state_mismatch_with_unsafe_path(self):
        request = self.make_request()
        assert len(get_messages(request)) == 0
        response = self.render_error(
            request, views.ERROR_STATE_MISMATCH,
            next_path='https://www.google.com/')
        assert response.status_code == 302
        messages = get_messages(request)
        assert len(messages) == 1
        assert 'could not be logged in' in next(iter(messages)).message
        assert_url_equal(response['location'], self.login_url())


class TestRenderErrorJSON(TestCase):

    def setUp(self):
        patcher = mock.patch('olympia.accounts.views.Response')
        self.Response = patcher.start()
        self.addCleanup(patcher.stop)

    def make_request(self):
        return APIRequestFactory().post(reverse('accounts.login'))

    def render_error(self, error):
        views.render_error(self.make_request(), error, format='json')

    def test_unknown_error(self):
        self.render_error('not-an-error')
        self.Response.assert_called_with({'error': 'not-an-error'}, status=422)

    def test_error_no_profile(self):
        self.render_error(views.ERROR_NO_PROFILE)
        self.Response.assert_called_with(
            {'error': views.ERROR_NO_PROFILE}, status=401)

    def test_error_state_mismatch(self):
        self.render_error(views.ERROR_STATE_MISMATCH)
        self.Response.assert_called_with(
            {'error': views.ERROR_STATE_MISMATCH}, status=400)


class TestWithUser(TestCase):

    def setUp(self):
        self.fxa_identify = self.patch(
            'olympia.accounts.views.verify.fxa_identify')
        self.find_user = self.patch('olympia.accounts.views.find_user')
        self.render_error = self.patch('olympia.accounts.views.render_error')
        self.request = mock.MagicMock()
        self.user = AnonymousUser()
        self.request.user = self.user
        self.request.session = {'fxa_state': 'some-blob'}

    @views.with_user(format='json')
    def fn(*args, **kwargs):
        return args, kwargs

    def test_profile_exists_with_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_exists_with_user_and_path(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        # "/a/path/?" gets URL safe base64 encoded to L2EvcGF0aC8_.
        self.request.data = {
            'code': 'foo',
            'state': u'some-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode('/a/path/?')),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': '/a/path/?',
        }

    def test_profile_exists_with_user_and_path_stripped_padding(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        # "/foo" gets URL safe base64 encoded to L2Zvbw== so it will be L2Zvbw.
        self.request.data = {
            'code': 'foo',
            'state': u'some-blob:{next_path}'.format(next_path='L2Zvbw'),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': '/foo',
        }

    def test_profile_exists_with_user_and_path_bad_encoding(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': u'some-blob:/raw/path',
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_exists_with_user_and_empty_path(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': u'some-blob:',
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_exists_with_user_and_path_is_not_safe(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': u'some-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode('https://www.google.com')),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_exists_no_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = None
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': None,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_does_not_exist(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_NO_PROFILE, next_path=None,
            format='json')
        assert not self.find_user.called

    def test_code_not_provided(self):
        self.request.data = {'hey': 'hi', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_NO_CODE, next_path=None, format='json')
        assert not self.find_user.called
        assert not self.fxa_identify.called

    @mock.patch.object(views, 'generate_api_token')
    def test_logged_in_disallows_login(self, generate_api_token_mock):
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{}'.format(base64.urlsafe_b64encode('/next')),
        }
        self.user = UserProfile()
        self.request.user = self.user
        assert self.user.is_authenticated()
        self.request.COOKIES = {views.API_TOKEN_COOKIE: 'foobar'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_AUTHENTICATED, next_path='/next',
            format='json')
        assert not self.find_user.called
        assert self.render_error.return_value.set_cookie.call_count == 0
        assert generate_api_token_mock.call_count == 0

    @mock.patch.object(views, 'generate_api_token', lambda u: 'fake-api-token')
    def test_already_logged_in_add_api_token_cookie_if_missing(self):
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{}'.format(base64.urlsafe_b64encode('/next')),
        }
        self.user = UserProfile()
        self.request.user = self.user
        assert self.user.is_authenticated()
        self.request.COOKIES = {}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_AUTHENTICATED, next_path='/next',
            format='json')
        assert not self.find_user.called
        response = self.render_error.return_value
        assert response.set_cookie.call_count == 1
        response.set_cookie.assert_called_with(
            views.API_TOKEN_COOKIE,
            'fake-api-token',
            max_age=settings.SESSION_COOKIE_AGE,
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=settings.SESSION_COOKIE_HTTPONLY)

    def test_state_does_not_match(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'other-blob:{}'.format(base64.urlsafe_b64encode('/next')),
        }
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_STATE_MISMATCH, next_path='/next',
            format='json')

    def test_dynamic_configuration(self):
        fxa_config = {'some': 'config'}

        class LoginView(object):
            def get_fxa_config(self, request):
                return fxa_config

            @views.with_user(format='json')
            def post(*args, **kwargs):
                return args, kwargs

        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        LoginView().post(self.request)
        self.fxa_identify.assert_called_with('foo', config=fxa_config)


class TestRegisterUser(TestCase):

    def setUp(self):
        self.request = APIRequestFactory().get('/register')
        self.identity = {'email': 'me@yeahoo.com', 'uid': '9005'}
        patcher = mock.patch('olympia.accounts.views.login')
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_user_is_created(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        views.register_user(self.request, self.identity)
        assert user_qs.exists()
        user = user_qs.get()
        assert user.username.startswith('anonymous-')
        assert user.fxa_id == '9005'
        assert user.auth_id
        self.login.assert_called_with(self.request, user)

    def test_username_taken_creates_user(self):
        UserProfile.objects.create(
            email='you@yeahoo.com', username='me@yeahoo.com')
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        views.register_user(self.request, self.identity)
        assert user_qs.exists()
        user = user_qs.get()
        assert user.username.startswith('anonymous-')
        assert user.fxa_id == '9005'


@override_settings(FXA_CONFIG={
    'foo': {'FOO': 123},
    'bar': {'BAR': 456},
    'baz': {'BAZ': 789},
})
class TestFxAConfigMixin(TestCase):

    class DefaultConfig(views.FxAConfigMixin):
        DEFAULT_FXA_CONFIG_NAME = 'bar'

    class MultipleConfigs(views.FxAConfigMixin):
        DEFAULT_FXA_CONFIG_NAME = 'baz'
        ALLOWED_FXA_CONFIGS = ['foo', 'baz']

    def test_default_only_no_config(self):
        request = RequestFactory().get('/login')
        config = self.DefaultConfig().get_fxa_config(request)
        assert config == {'BAR': 456}

    def test_default_only_not_allowed(self):
        request = RequestFactory().get('/login?config=foo')
        config = self.DefaultConfig().get_fxa_config(request)
        assert config == {'BAR': 456}

    def test_default_only_allowed(self):
        request = RequestFactory().get('/login?config=bar')
        config = self.DefaultConfig().get_fxa_config(request)
        assert config == {'BAR': 456}

    def test_config_is_allowed(self):
        request = RequestFactory().get('/login?config=foo')
        config = self.MultipleConfigs().get_fxa_config(request)
        assert config == {'FOO': 123}

    def test_config_is_default(self):
        request = RequestFactory().get('/login?config=baz')
        config = self.MultipleConfigs().get_fxa_config(request)
        assert config == {'BAZ': 789}

    def test_config_is_not_allowed(self):
        request = RequestFactory().get('/login?config=bar')
        config = self.MultipleConfigs().get_fxa_config(request)
        assert config == {'BAZ': 789}


@override_settings(FXA_CONFIG={'current-config': FXA_CONFIG})
class TestLoginBaseView(WithDynamicEndpoints, TestCase):

    class LoginView(views.LoginBaseView):
        DEFAULT_FXA_CONFIG_NAME = 'current-config'

    def setUp(self):
        super(TestLoginBaseView, self).setUp()
        self.endpoint(self.LoginView, r'^login/')
        self.url = '/en-US/firefox/login/'
        self.initialize_session({'fxa_state': 'some-blob'})
        self.update_user = self.patch('olympia.accounts.views.update_user')
        self.fxa_identify = self.patch(
            'olympia.accounts.views.verify.fxa_identify')

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_CODE
        assert not self.update_user.called

    def test_wrong_state(self):
        response = self.client.post(
            self.url, {'code': 'foo', 'state': 'a-different-blob'})
        assert response.status_code == 400
        assert response.data['error'] == views.ERROR_STATE_MISMATCH
        assert not self.update_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 401
        assert response.data['error'] == views.ERROR_NO_PROFILE
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.update_user.called

    def test_no_amo_account_cant_login(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com', 'uid': '5'}
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_USER
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.update_user.called

    def test_login_success(self):
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'code', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        token = response.data['token']
        verify = WebTokenAuthentication().authenticate_token(token)
        assert verify[0] == user
        self.update_user.assert_called_with(user, identity)

    def test_multiple_accounts_found(self):
        """Test that login fails if the user is logged in but the fxa_id is
        set on a different UserProfile."""
        UserProfile.objects.create(email='real@yeahoo.com', username='foo')
        UserProfile.objects.create(
            email='different@yeahoo.com', fxa_id='9005', username='bar')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9005'}
        with self.assertRaises(UserProfile.MultipleObjectsReturned):
            self.client.post(
                self.url, {'code': 'code', 'state': 'some-blob'})
        assert not self.update_user.called


class TestRegisterView(BaseAuthenticationView):
    view_name = 'accounts.register'

    def setUp(self):
        super(TestRegisterView, self).setUp()
        self.initialize_session({'fxa_state': 'some-blob'})
        self.register_user = self.patch('olympia.accounts.views.register_user')

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_CODE
        assert not self.register_user.called

    def test_wrong_state(self):
        response = self.client.post(
            self.url, {'code': 'foo', 'state': 'wrong-blob'})
        assert response.status_code == 400
        assert response.data['error'] == views.ERROR_STATE_MISMATCH
        assert not self.register_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 401
        assert response.data['error'] == views.ERROR_NO_PROFILE
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.register_user.called

    def test_register_success(self):
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        user = UserProfile(username='foobar', email=identity['email'])
        self.register_user.return_value = user
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
        assert (response.cookies['api_auth_token'].value ==
                response.data['token'])
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        self.register_user.assert_called_with(mock.ANY, identity)


class TestAuthenticateView(BaseAuthenticationView):
    view_name = 'accounts.authenticate'

    def setUp(self):
        super(TestAuthenticateView, self).setUp()
        self.fxa_state = '1cd2ae9d'
        self.initialize_session({'fxa_state': self.fxa_state})
        self.login_user = self.patch('olympia.accounts.views.login_user')
        self.register_user = self.patch('olympia.accounts.views.register_user')

    def login_url(self, **params):
        return absolutify(urlparams(reverse('users.login'), **params))

    def test_write_is_used(self, **params):
        with mock.patch('olympia.amo.models.use_master') as use_master:
            self.client.get(self.url)
        assert use_master.called

    def test_no_code_provided(self):
        response = self.client.get(self.url)
        assert response.status_code == 302
        # Messages seem to appear in the context for some reason.
        assert 'could not be parsed' in response.context['title']
        assert_url_equal(response['location'], self.login_url())
        assert not self.login_user.called
        assert not self.register_user.called

    def test_wrong_state(self):
        response = self.client.get(
            self.url, {'code': 'foo', 'state': '9f865be0'})
        assert response.status_code == 302
        assert 'could not be logged in' in response.context['title']
        assert_url_equal(response['location'], self.login_url())
        assert not self.login_user.called
        assert not self.register_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state})
        assert response.status_code == 302
        assert ('Your Firefox Account could not be found'
                in response.context['title'])
        assert_url_equal(response['location'], self.login_url())
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        assert not self.register_user.called

    def test_success_no_account_registers(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        self.register_user.side_effect = (
            lambda r, i: UserProfile.objects.create(
                username='foo', email='me@yeahoo.com', fxa_id='e0b6f'))
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state})
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)
        token = response.cookies['api_auth_token'].value
        verify = WebTokenAuthentication().authenticate_token(token)
        assert verify[0] == UserProfile.objects.get(username='foo')

    def test_register_redirects_edit(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        user = UserProfile(username='foo', email='me@yeahoo.com')
        self.register_user.return_value = user
        response = self.client.get(self.url, {
            'code': 'codes!!',
            'state': ':'.join(
                [self.fxa_state, base64.urlsafe_b64encode('/go/here')]),
        })
        # This 302s because the user isn't logged in due to mocking.
        self.assertRedirects(
            response, reverse('users.edit'), target_status_code=302)
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)

    @mock.patch('olympia.accounts.views.AuthenticateView.ALLOWED_FXA_CONFIGS',
                ['default', 'skip'])
    def test_register_redirects_next_when_config_says_to(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        user = UserProfile(username='foo', email='me@yeahoo.com')
        self.register_user.return_value = user
        response = self.client.get(self.url, {
            'code': 'codes!!',
            'state': ':'.join(
                [self.fxa_state, base64.urlsafe_b64encode('/go/here')]),
            'config': 'skip',
        })
        self.fxa_identify.assert_called_with(
            'codes!!', config=SKIP_REDIRECT_FXA_CONFIG)
        self.assertRedirects(
            response, '/go/here', fetch_redirect_response=False)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)

    def test_success_with_account_logs_in(self):
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com', fxa_id='10')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'code', 'state': self.fxa_state})
        self.assertRedirects(response, reverse('home'))
        token = response.cookies['api_auth_token'].value
        verify = WebTokenAuthentication().authenticate_token(token)
        assert verify[0] == user
        self.login_user.assert_called_with(mock.ANY, user, identity)
        assert not self.register_user.called

    def test_log_in_redirects_to_next_path(self):
        user = UserProfile.objects.create(email='real@yeahoo.com', fxa_id='10')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(self.url, {
            'code': 'code',
            'state': ':'.join([
                self.fxa_state,
                base64.urlsafe_b64encode('/en-US/firefox/a/path')]),
        })
        self.assertRedirects(
            response, '/en-US/firefox/a/path', target_status_code=404)
        self.login_user.assert_called_with(mock.ANY, user, identity)
        assert not self.register_user.called

    def test_log_in_sets_fxa_data_and_redirects(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(self.url, {
            'code': 'code',
            'state': ':'.join([
                self.fxa_state,
                base64.urlsafe_b64encode('/en-US/firefox/a/path')]),
        })
        self.assertRedirects(
            response, '/en-US/firefox/a/path', target_status_code=404)
        self.login_user.assert_called_with(mock.ANY, user, identity)
        assert not self.register_user.called


class TestProfileView(APIKeyAuthTestCase):

    def setUp(self):
        self.create_api_user()
        self.url = reverse('accounts.profile')
        self.cls = resolve(self.url).func.cls
        super(TestProfileView, self).setUp()

    def test_good(self):
        res = self.get(self.url)
        assert res.status_code == 200
        assert res.data['email'] == 'a@m.o'

    def test_auth_required(self):
        self.auth_required(self.cls)

    def test_verbs_allowed(self):
        self.verbs_allowed(self.cls, ['get'])


class TestAccountSuperCreate(APIKeyAuthTestCase):

    def setUp(self):
        super(TestAccountSuperCreate, self).setUp()
        create_switch('super-create-accounts', active=True)
        self.create_api_user()
        self.url = reverse('accounts.super-create')
        group = Group.objects.create(
            name='Account Super Creators',
            rules='Accounts:SuperCreate')
        GroupUser.objects.create(group=group, user=self.user)

    def test_require_auth(self):
        self.auth_required(views.AccountSuperCreate)

    def test_require_a_waffle_switch(self):
        Switch.objects.all().delete()
        res = self.post(self.url, {})
        assert res.status_code == 404, res.content

    def test_requesting_user_must_have_access(self):
        self.user.groups.all().delete()
        res = self.post(self.url, {})
        assert res.status_code == 403, res.content
        assert res.data['detail'] == (
            'You do not have permission to perform this action.')

    def test_a_new_user_is_created_and_logged_in(self):
        res = self.post(self.url, {})
        assert res.status_code == 201, res.content
        data = res.data

        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert user.username == data['username']
        assert user.email == data['email']
        assert user.email.endswith('@addons.mozilla.org')
        assert user.fxa_id == data['fxa_id']
        assert user.display_name == data['display_name']
        assert data['session_cookie']['name']
        assert data['session_cookie']['value']
        encoded = '{name}={value}'.format(**data['session_cookie'])
        assert data['session_cookie']['encoded'] == encoded

    def test_requires_a_valid_email(self):
        res = self.post(self.url, {'email': 'not.a.valid.email'})
        assert res.status_code == 422, res.content
        assert res.data['errors'] == {
            'email': ['Enter a valid email address.'],
        }

    def test_create_a_user_with_custom_email(self):
        email = 'shanghaibotnet8000@hotmail.zh'
        res = self.post(self.url, {'email': email})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert user.email == email

    def test_create_a_user_with_custom_fxa_id(self):
        fxa_id = '6d940dd41e636cc156074109b8092f96'
        res = self.post(self.url, {'fxa_id': fxa_id})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert user.fxa_id == fxa_id

    def test_create_a_user_with_custom_username(self):
        username = 'shanghaibotnet8000'
        res = self.post(self.url, {'username': username})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert user.username == username

    def test_cannot_create_user_with_duplicate_email(self):
        email = 'shanghaibotnet8000@hotmail.zh'
        user = UserProfile.objects.all()[0]
        user.email = email
        user.save()

        res = self.post(self.url, {'email': email})
        assert res.status_code == 422, res.content
        assert res.data['errors'] == {
            'email': ['Someone with this email already exists in the system'],
        }

    def test_cannot_create_user_with_duplicate_username(self):
        username = 'shanghaibotnet8000'
        user = UserProfile.objects.all()[0]
        user.username = username
        user.save()

        res = self.post(self.url, {'username': username})
        assert res.status_code == 422, res.content
        assert res.data['errors'] == {
            'username': [
                'Someone with this username already exists in the system'],
        }

    def test_cannot_add_user_to_group_when_one_doesnt_exist(self):
        res = self.post(self.url, {'group': 'reviewer'})
        assert res.status_code == 422, res.content
        assert res.data['errors'] == {
            'group': [
                'Could not find a permissions group with the exact rules '
                'needed.'],
        }

    def test_can_create_a_reviewer_user(self):
        Group.objects.create(rules='Addons:Review', name='reviewer group')
        res = self.post(self.url, {'group': 'reviewer'})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert action_allowed_user(user, 'Addons', 'Review')

    def test_can_create_an_admin_user(self):
        group = Group.objects.create(rules='*:*', name='admin group')
        res = self.post(self.url, {'group': 'admin'})

        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert action_allowed_user(user, 'Any', 'DamnThingTheyWant')
        assert res.data['groups'] == [(group.pk, group.name, group.rules)]


class TestParseNextPath(TestCase):

    def test_plain_path(self):
        parts = ['deadcafe', 'L2VuLVVTL2FkZG9ucy9teS1hZGRvbi8']
        next_path = views.parse_next_path(parts)
        assert next_path == '/en-US/addons/my-addon/'

    def test_unicode_path(self):
        parts = [
            'deadcafe',
            'L2VuLVVTL2ZpcmVmb3gvYWRkb24vZMSZbMOuY8Otw7jDuXMtcMOkw7HEjcOla8SZL'
            'z9zcmM9aHAtZGwtZmVhdHVyZWQ',
        ]
        next_path = views.parse_next_path(parts)
        assert next_path == (
            u'/en-US/firefox/addon/dęlîcíøùs-päñčåkę/?src=hp-dl-featured')


class TestSessionView(TestCase):
    def login_user(self, user):
        identity = {
            'username': user.username,
            'email': user.email,
            'uid': user.fxa_id,
        }
        self.initialize_session({'fxa_state': 'myfxastate'})
        with mock.patch(
                'olympia.accounts.views.verify.fxa_identify',
                lambda code, config: identity):
            response = self.client.get(
                '{url}?code={code}&state={state}'.format(
                    url=reverse('accounts.authenticate'),
                    state='myfxastate',
                    code='thecode'))
            token = response.cookies[views.API_TOKEN_COOKIE].value
            assert token
            verify = WebTokenAuthentication().authenticate_token(token)
            assert verify[0] == user
            assert self.client.session['_auth_user_id'] == str(user.id)
            return token

    def test_delete_when_authenticated(self):
        user = user_factory(fxa_id='123123412')
        token = self.login_user(user)
        authorization = 'Bearer {token}'.format(token=token)
        response = self.client.delete(
            reverse('accounts.session'), HTTP_AUTHORIZATION=authorization)
        assert not response.cookies[views.API_TOKEN_COOKIE].value
        assert not self.client.session.get('_auth_user_id')

    def test_delete_when_unauthenticated(self):
        response = self.client.delete(reverse('accounts.session'))
        assert response.status_code == 401
