import base64
import json
import time
from datetime import datetime
from ipaddress import IPv4Address
from os import path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django import http
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import AnonymousUser
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

import freezegun
import jwt
import responses
from rest_framework import exceptions
from rest_framework.settings import api_settings
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView
from waffle.models import Switch
from waffle.testutils import override_switch

from olympia import amo
from olympia.access.acl import action_allowed_for
from olympia.access.models import Group, GroupUser
from olympia.accounts import verify, views
from olympia.accounts.views import FxaNotificationView
from olympia.activity.models import ActivityLog, IPLog
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    APITestClientSessionID,
    InitializeSessionMixin,
    TestCase,
    WithDynamicEndpoints,
    addon_factory,
    assert_url_equal,
    create_switch,
    reverse_ns,
    user_factory,
)
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.users.models import UserNotification, UserProfile
from olympia.users.notifications import (
    NOTIFICATIONS_BY_ID,
    NOTIFICATIONS_COMBINED,
    REMOTE_NOTIFICATIONS_BY_BASKET_ID,
)
from olympia.users.utils import UnsubscribeCode


FXA_CONFIG = {
    'client_id': 'amodefault',
}
SKIP_REDIRECT_FXA_CONFIG = {
    'client_id': 'amodefault',
}


@override_settings(
    FXA_CONFIG={'current-config': FXA_CONFIG},
    DEFAULT_FXA_CONFIG_NAME='current-config',
)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/v1')
class TestLoginStartBaseView(WithDynamicEndpoints, TestCase):
    def setUp(self):
        super().setUp()
        self.endpoint(views.LoginStartView, r'^login/start/')
        self.url = '/en-US/firefox/login/start/'
        self.initialize_session({})

    def test_state_is_set(self):
        self.initialize_session({})
        assert 'fxa_state' not in self.client.session
        state = 'somerandomstate'
        with mock.patch('olympia.accounts.utils.generate_fxa_state', lambda: state):
            self.client.get(self.url)
        assert 'fxa_state' in self.client.session
        assert self.client.session['fxa_state'] == state

    def test_redirect_url_is_correct(self):
        self.initialize_session({})
        with mock.patch(
            'olympia.accounts.utils.generate_fxa_state', lambda: 'arandomstring'
        ):
            response = self.client.get(self.url)
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        url = urlparse(response['location'])
        redirect = '{scheme}://{netloc}{path}'.format(
            scheme=url.scheme, netloc=url.netloc, path=url.path
        )
        assert redirect == 'https://accounts.firefox.com/v1/authorization'
        assert parse_qs(url.query) == {
            'access_type': ['offline'],
            'client_id': ['amodefault'],
            'scope': ['profile openid'],
            'state': ['arandomstring'],
        }

    def test_state_is_not_overriden(self):
        self.initialize_session({'fxa_state': 'thisisthestate'})
        response = self.client.get(self.url)
        assert self.client.session['fxa_state'] == 'thisisthestate'
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )

    def test_to_is_included_in_redirect_state(self):
        path = b'/addons/unlisted-addon/'
        # The =s will be stripped from the URL.
        assert b'=' in base64.urlsafe_b64encode(path)
        state = 'somenewstatestring'
        self.initialize_session({})
        with mock.patch('olympia.accounts.utils.generate_fxa_state', lambda: state):
            response = self.client.get(self.url, data={'to': path})
        assert self.client.session['fxa_state'] == state
        url = urlparse(response['location'])
        query = parse_qs(url.query)
        state_parts = query['state'][0].split(':')
        assert len(state_parts) == 2
        assert state_parts[0] == state
        assert '=' not in state_parts[1]
        assert base64.urlsafe_b64decode(state_parts[1] + '====') == path

    def test_to_is_excluded_when_unsafe(self):
        path = 'https://www.google.com'
        self.initialize_session({})
        response = self.client.get(f'{self.url}?to={path}')
        url = urlparse(response['location'])
        query = parse_qs(url.query)
        assert ':' not in query['state'][0]

    def test_allows_code_manager_url(self):
        self.initialize_session({})
        code_manager_url = 'https://code.example.org'
        to = f'{code_manager_url}/foobar'
        with override_settings(CODE_MANAGER_URL=code_manager_url):
            response = self.client.get(f'{self.url}?to={to}')
        url = urlparse(response['location'])
        query = parse_qs(url.query)
        state_parts = query['state'][0].split(':')
        assert base64.urlsafe_b64decode(state_parts[1] + '====') == to.encode()

    def test_allows_absolute_urls(self):
        self.initialize_session({})
        domain = 'example.org'
        to = f'https://{domain}/foobar'
        with override_settings(DOMAIN=domain):
            response = self.client.get(f'{self.url}?to={to}')
        url = urlparse(response['location'])
        query = parse_qs(url.query)
        state_parts = query['state'][0].split(':')
        assert base64.urlsafe_b64decode(state_parts[1] + '====') == to.encode()


def has_cors_headers(response, origin='https://addons-frontend'):
    return (
        response['Access-Control-Allow-Origin'] == origin
        and response['Access-Control-Allow-Credentials'] == 'true'
    )


class TestLoginStartView(TestCase):
    @override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=True)
    def test_redirect_url_fake_fxa_auth(self):
        response = self.client.get(reverse_ns('accounts.login_start'))
        assert response.status_code == 302
        url = urlparse(response['location'])
        assert url.path == reverse('fake-fxa-authorization')
        query = parse_qs(url.query)
        assert query['state']


class TestLoginUserAndRegisterUser(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/login')
        self.enable_messages_and_session(self.request)
        self.user = UserProfile.objects.create(email='real@yeahoo.com', fxa_id='9001')
        self.identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        # Add a patch with wraps= to spy around django.contrib.auth.login()
        patcher = mock.patch('olympia.accounts.views.login', wraps=login)
        self.login_mock = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.core.get_remote_addr')
        get_remote_addr_mock = patcher.start()
        get_remote_addr_mock.return_value = '8.8.8.8'
        self.addCleanup(patcher.stop)

    def test_user_gets_logged_in(self):
        views.login_user(self.__class__, self.request, self.user, self.identity)
        self.login_mock.assert_called_with(self.request, self.user)

    def test_login_is_logged(self):
        self.user.update(last_login=self.days_ago(42))
        views.login_user(self.__class__, self.request, self.user, self.identity)
        self.login_mock.assert_called_with(self.request, self.user)
        self.assertCloseToNow(self.user.last_login)
        assert self.user.last_login_ip == '8.8.8.8'
        assert (
            ActivityLog.objects.filter(user=self.user, action=amo.LOG.LOG_IN.id).count()
            == 1
        )
        assert (
            ActivityLog.objects.filter(
                user=self.user, action=amo.LOG.LOG_IN_API_TOKEN.id
            ).count()
            == 0
        )
        assert IPLog.objects.all().count() == 1
        assert IPLog.objects.get().ip_address_binary == IPv4Address('8.8.8.8')

    def test_email_address_can_change(self):
        self.user.update(email='different@yeahoo.com')
        views.login_user(self.__class__, self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'

    def test_fxa_id_can_be_set(self):
        self.user.update(fxa_id=None)
        views.login_user(self.__class__, self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'

    def test_auth_id_updated_if_none(self):
        self.user.update(auth_id=None)
        views.login_user(self.__class__, self.request, self.user, self.identity)
        self.user.reload()
        assert self.user.auth_id

    def test_register_user(self):
        identity = {'email': 'new@yeahoo.com', 'uid': '424242'}
        with mock.patch('django_statsd.clients.statsd.incr') as incr_mock:
            views.register_user(identity)
        assert UserProfile.objects.count() == 2
        user = UserProfile.objects.get(email='new@yeahoo.com')
        assert user.fxa_id == '424242'
        views.login_user(self.__class__, self.request, user, identity)
        self.assertCloseToNow(user.last_login)
        assert user.last_login_ip == '8.8.8.8'
        incr_mock.assert_called_with('accounts.account_created_from_fxa')

        # The other user wasn't affected.
        self.user.reload()
        assert self.user.pk != user.pk
        assert self.user.auth_id != user.auth_id
        assert self.user.last_login != user.last_login
        assert self.user.last_login_ip != user.last_login_ip
        assert self.user.fxa_id != user.fxa_id
        assert self.user.email != user.email

    def test_reregister_user(self):
        self.user.update(deleted=True)
        with mock.patch('django_statsd.clients.statsd.incr') as incr_mock:
            views.reregister_user(self.user)
        assert UserProfile.objects.count() == 1
        user = self.user.reload()
        assert not user.deleted
        views.login_user(self.__class__, self.request, user, self.identity)
        self.assertCloseToNow(user.last_login)
        assert user.last_login_ip == '8.8.8.8'
        incr_mock.assert_called_with('accounts.account_created_from_fxa')

    def test_login_with_token_data(self):
        token_data = {
            'refresh_token': 'somerefresh_token',
            'access_token_expiry': time.time() + 12345,
            'config_name': 'someconfigname',
        }
        views.login_user(
            self.__class__, self.request, self.user, self.identity, token_data
        )
        self.login_mock.assert_called_with(self.request, self.user)
        assert (
            self.request.session['fxa_access_token_expiry']
            == token_data['access_token_expiry']
        )
        assert self.request.session['fxa_refresh_token'] == token_data['refresh_token']
        assert self.request.session['fxa_config_name'] == token_data['config_name']


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
        UserProfile.objects.create(fxa_id='9999', email='me@amo.ca', username='me')
        UserProfile.objects.create(fxa_id='8888', email='you@amo.ca', username='you')
        with self.assertRaises(UserProfile.MultipleObjectsReturned):
            views.find_user({'uid': '9999', 'email': 'you@amo.ca'})

    def test_find_user_banned(self):
        UserProfile.objects.create(
            fxa_id='abc',
            email='me@amo.ca',
            deleted=True,
            banned=datetime.now(),
        )
        with self.assertRaises(exceptions.PermissionDenied):
            views.find_user({'uid': 'abc', 'email': 'you@amo.ca'})

    def test_find_user_deleted(self):
        user = UserProfile.objects.create(fxa_id='abc', email='me@amo.ca', deleted=True)
        assert views.find_user({'uid': 'abc', 'email': 'you@amo.ca'}) == user

    def test_find_user_mozilla(self):
        task_user = user_factory(id=settings.TASK_USER_ID, fxa_id='abc')
        with self.assertRaises(exceptions.PermissionDenied):
            views.find_user({'uid': '123456', 'email': task_user.email})
        with self.assertRaises(exceptions.PermissionDenied):
            views.find_user({'uid': task_user.fxa_id, 'email': 'doesnt@matta'})


class TestWithUser(TestCase):
    token_data = {
        'id_token': 'someopenidtoken',
        'access_token': 'someaccesstoken',
        'refresh_token': 'somerefresh_token',
        'expires_in': 12345,
        'access_token_expiry': time.time() + 12345,
    }

    def setUp(self):
        self.fxa_identify = self.patch('olympia.accounts.views.verify.fxa_identify')
        self.find_user = self.patch('olympia.accounts.views.find_user')
        self.request = mock.MagicMock()
        self.user = AnonymousUser()
        self.request.user = self.user
        self.request.session = {'fxa_state': 'some-blob'}

    def get_fxa_config(self, request):
        return settings.FXA_CONFIG[self.get_config_name(request)]

    def get_config_name(self, request):
        return settings.DEFAULT_FXA_CONFIG_NAME

    @views.with_user
    def fn(*args, **kwargs):
        return args, kwargs

    def test_profile_exists_with_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
            'token_data': self.token_data,
        }

    def test_profile_exists_with_user_and_path(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        # "/a/path/?" gets URL safe base64 encoded to L2EvcGF0aC8_.
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'/a/path/?'))
            ),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': '/a/path/?',
            'token_data': self.token_data,
        }

    def test_profile_exists_with_user_and_path_stripped_padding(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        # "/foo" gets URL safe base64 encoded to L2Zvbw== so it will be L2Zvbw.
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{next_path}'.format(next_path='L2Zvbw'),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': '/foo',
            'token_data': self.token_data,
        }

    def test_profile_exists_with_user_and_path_bad_encoding(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:/raw/path',
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
            'token_data': self.token_data,
        }

    def test_profile_exists_with_user_and_empty_path(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:',
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
            'token_data': self.token_data,
        }

    def test_profile_exists_with_user_and_path_is_not_safe(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'https://www.google.com'))
            ),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
            'token_data': self.token_data,
        }

    def test_profile_exists_no_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = None
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': None,
            'identity': identity,
            'next_path': None,
            'token_data': self.token_data,
        }

    def test_profile_does_not_exist(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        response = self.fn(self.request)
        self.assertRedirects(response, '/en-US/firefox/', fetch_redirect_response=False)
        assert not self.find_user.called

    def test_code_not_provided(self):
        self.request.data = {'hey': 'hi', 'state': 'some-blob'}
        response = self.fn(self.request)
        self.assertRedirects(response, '/en-US/firefox/', fetch_redirect_response=False)
        assert not self.find_user.called
        assert not self.fxa_identify.called

    def test_logged_in_disallows_login(self):
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{}'.format(
                force_str(base64.urlsafe_b64encode(b'/next'))
            ),
        }
        self.user = UserProfile()
        self.request.user = self.user
        assert self.user.is_authenticated
        response = self.fn(self.request)
        self.assertRedirects(response, '/next', fetch_redirect_response=False)
        assert not response.cookies
        assert not self.find_user.called

    def test_state_does_not_match(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'other-blob:{}'.format(
                force_str(base64.urlsafe_b64encode(b'/next'))
            ),
        }
        response = self.fn(self.request)
        # next path is ignored as state is not reliable.
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    @override_settings(
        FXA_CONFIG={'a_conf': {'client_id': 'clientid', 'client_secret': 'supersikret'}}
    )
    def test_non_default_fxa_configuration_with_actual_apiview(self):
        class LoginView(APIView):
            @views.with_user
            def get(*args, **kwargs):
                return super().get(*args, **kwargs)

        fxa_config_name = 'a_conf'
        fxa_state = 'someblob'
        fxa_code = 'foo'
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        # We're emulating an APIView, so we have to provide a true request
        # object and let DRF processing make a DRF Request out of it by calling
        # dispatch().
        self.request = APIRequestFactory().get(
            f'/?config={fxa_config_name}&code={fxa_code}&state={fxa_state}'
        )
        self.request.session = {'fxa_state': fxa_state}
        LoginView().dispatch(self.request)
        self.fxa_identify.assert_called_with(
            fxa_code, config={'client_id': 'clientid', 'client_secret': 'supersikret'}
        )

    def _test_should_redirect_for_two_factor_auth(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'/a/path/?'))
            ),
        }
        # @with_user should return a redirect response directly in that case.
        response = self.fn(self.request)

        # Query params should be kept on the redirect to FxA, with
        # acr_values=AAL2 added to force two-factor auth on FxA side and
        # id_token_hint passed with the openid token retrieved from FxA as well
        # as prompt=none to avoid the need for the user to re-authenticate.
        assert response.status_code == 302
        url = urlparse(response['Location'])
        base = '{scheme}://{netloc}{path}'.format(
            scheme=url.scheme, netloc=url.netloc, path=url.path
        )
        fxa_config = settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME]
        assert base == '{host}{path}'.format(
            host=settings.FXA_OAUTH_HOST, path='/authorization'
        )
        query = parse_qs(url.query)
        next_path = base64.urlsafe_b64encode(b'/a/path/?').rstrip(b'=')
        assert query == {
            'access_type': ['offline'],
            'acr_values': ['AAL2'],
            'client_id': [fxa_config['client_id']],
            'id_token_hint': ['someopenidtoken'],
            'prompt': ['none'],
            'scope': ['profile openid'],
            'state': [f'some-blob:{force_str(next_path)}'],
        }

    def _test_should_continue_without_redirect_for_two_factor_auth(
        self, *, identity=None
    ):
        identity = identity or {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity, self.token_data
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'/a/path/?'))
            ),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': '/a/path/?',
            'token_data': self.token_data,
        }

    def test_addon_developer_should_redirect_for_two_factor_auth(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        # They have developed a theme, but also an extension, so they will need
        # 2FA.
        addon_factory(users=[self.user])
        addon_factory(users=[self.user], type=amo.ADDON_STATICTHEME)
        self._test_should_redirect_for_two_factor_auth()

    def test_special_user_should_redirect_for_two_factor_auth(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        # User isn't a developer but is part of a group.
        self.grant_permission(self.user, 'Some:Thing')
        self._test_should_redirect_for_two_factor_auth()

    def test_user_should_redirect_for_two_factor_auth_flag_user_specific(self):
        self.user = user_factory()
        flag = self.create_flag(
            '2fa-enforcement-for-developers-and-special-users', everyone=False
        )
        flag.users.add(self.user)
        # User isn't a developer but is part of a group.
        self.grant_permission(self.user, 'Some:Thing')
        # The flag is enabled for that user.
        self._test_should_redirect_for_two_factor_auth()

        # Others should be unaffected as the flag is only set for a specific
        # user.
        self.user = user_factory()
        self.grant_permission(self.user, 'Some:Thing')
        self._test_should_continue_without_redirect_for_two_factor_auth()

    def test_theme_developer_should_not_redirect_for_two_factor_auth(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        addon_factory(users=[self.user], type=amo.ADDON_STATICTHEME)
        self._test_should_continue_without_redirect_for_two_factor_auth()

    def test_addon_developer_already_using_two_factor_should_continue(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        addon_factory(users=[self.user])
        identity = {
            'uid': '1234',
            'email': 'hey@yo.it',
            'twoFactorAuthentication': True,
        }
        self._test_should_continue_without_redirect_for_two_factor_auth(
            identity=identity
        )

    def test_2fa_enforced_already_using_two_factor_should_continue(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        identity = {
            'uid': '1234',
            'email': 'hey@yo.it',
            'twoFactorAuthentication': True,
        }
        self.request.session['enforce_2fa'] = True
        self._test_should_continue_without_redirect_for_two_factor_auth(
            identity=identity
        )
        # Since the authentication was successful and satistified our 2FA
        # requirement, we removed the property from the session.
        assert 'enforce_2fa' not in self.request.session

    def test_2fa_enforced_on_this_view_should_redirect_for_two_factor_auth(self):
        self.create_flag('2fa-enforcement-for-developers-and-special-users')
        self.user = user_factory()
        self.request.session['enforce_2fa'] = True
        self._test_should_redirect_for_two_factor_auth()

    def test_waffle_flag_off_developer_without_2fa_should_continue(self):
        self.create_flag(
            '2fa-enforcement-for-developers-and-special-users', everyone=False
        )
        self.user = user_factory()
        addon_factory(users=[self.user])
        self._test_should_continue_without_redirect_for_two_factor_auth()

    def test_waffle_flag_off_enforced_2fa_should_have_no_effect(self):
        self.create_flag(
            '2fa-enforcement-for-developers-and-special-users', everyone=False
        )
        self.user = user_factory()
        self.request.session['enforce_2fa'] = True
        self._test_should_continue_without_redirect_for_two_factor_auth()

    @override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=True)
    def test_fake_fxa_auth(self):
        self.user = user_factory()
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'fake_fxa_email': self.user.email,
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'/a/path/?'))
            ),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs['user'] == self.user
        assert kwargs['identity']['email'] == self.user.email
        assert kwargs['identity']['uid'].startswith('fake_fxa_id-')
        assert len(kwargs['identity']['uid']) == 44  # 32 random chars + prefix
        assert kwargs['identity']['twoFactorAuthentication'] is None
        assert kwargs['next_path'] == '/a/path/?'
        assert self.fxa_identify.call_count == 0

    @override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=True)
    def test_fake_fxa_auth_with_2fa(self):
        self.user = user_factory()
        self.find_user.return_value = self.user
        self.request.data = {
            'code': 'foo',
            'fake_fxa_email': self.user.email,
            'fake_two_factor_authentication': 'true',
            'state': 'some-blob:{next_path}'.format(
                next_path=force_str(base64.urlsafe_b64encode(b'/a/path/?'))
            ),
        }
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs['user'] == self.user
        assert kwargs['identity']['email'] == self.user.email
        assert kwargs['identity']['uid'].startswith('fake_fxa_id-')
        assert len(kwargs['identity']['uid']) == 44  # 32 random chars + prefix
        assert kwargs['identity']['twoFactorAuthentication'] == 'true'
        assert kwargs['next_path'] == '/a/path/?'
        assert self.fxa_identify.call_count == 0


def empty_view(*args, **kwargs):
    return http.HttpResponse()


@override_settings(
    FXA_CONFIG={
        'default': FXA_CONFIG,
        'skip': SKIP_REDIRECT_FXA_CONFIG,
    }
)
class TestAuthenticateView(TestCase, InitializeSessionMixin):
    view_name = 'accounts.authenticate'
    client_class = APIClient
    api_version = 'auth'
    token_data = {
        'id_token': 'someopenidtoken',
        'access_token': 'someaccesstoken',
        'refresh_token': 'somerefresh_token',
        'expires_in': 12345,
        'access_token_expiry': time.time() + 12345,
    }

    def setUp(self):
        super().setUp()
        self.fxa_identify = self.patch('olympia.accounts.views.verify.fxa_identify')
        self.url = reverse_ns(self.view_name, api_version=self.api_version)
        self.fxa_state = '1cd2ae9d'
        self.initialize_session({'fxa_state': self.fxa_state})
        self.login_user = self.patch('olympia.accounts.views.login_user')
        self.register_user = self.patch('olympia.accounts.views.register_user')
        self.reregister_user = self.patch('olympia.accounts.views.reregister_user')
        self.user_edit_url = reverse('users.edit')

    def test_write_is_used(self, **params):
        with mock.patch('olympia.amo.models.use_primary_db') as use_primary_db:
            self.client.get(self.url)
        assert use_primary_db.called

    def test_no_code_provided(self):
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        # next path is ignored as state is not reliable.
        assert_url_equal(response['location'], '/')
        assert not self.login_user.called
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_wrong_state(self):
        response = self.client.get(self.url, {'code': 'foo', 'state': '9f865be0'})
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        # next path is ignored as state is not reliable.
        assert_url_equal(response['location'], '/')
        assert not self.login_user.called
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_error_from_fxa(self):
        response = self.client.get(self.url, {'error': 'foo', 'state': '9f865be0'})
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        # next path is ignored as state is not reliable.
        assert_url_equal(response['location'], '/')
        assert not self.login_user.called
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state}
        )
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        assert_url_equal(response['location'], '/en-US/firefox/')
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_success_deleted_account_reregisters(self):
        user = UserProfile.objects.create(
            email='real@yeahoo.com', fxa_id='10', deleted=True
        )
        identity = {'email': 'real@yeahoo.com', 'uid': '10'}
        self.fxa_identify.return_value = identity, self.token_data
        self.reregister_user.side_effect = lambda user: user.update(deleted=False)
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state}
        )
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        assert not self.register_user.called
        self.reregister_user.assert_called_with(user)

    def test_success_deleted_account_reregisters_with_force_2fa_waffle(self):
        self.create_switch('2fa-for-developers', active=True)
        self.test_success_deleted_account_reregisters()

    def test_success_no_account_registers(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda identity: UserProfile.objects.create(
            username='foo', email='me@yeahoo.com', fxa_id='e0b6f'
        )
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state}
        )
        assert response.status_code == 302
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_success_no_account_registers_with_force_2fa_waffle(self):
        self.create_switch('2fa-for-developers', active=True)
        self.test_success_no_account_registers()

    def test_register_redirects_edit(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda i: user_factory(email='me@yeahoo.com')
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            response = self.client.get(
                self.url,
                {
                    'code': 'codes!!',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(b'/go/here')),
                        ]
                    ),
                },
            )
            self.assertRedirects(
                response, self.user_edit_url + '?to=/go/here', target_status_code=200
            )
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_register_redirects_no_next_path(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda i: user_factory(email='me@yeahoo.com')
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            response = self.client.get(
                self.url,
                {
                    'code': 'codes!!',
                    'state': self.fxa_state,
                },
            )
            self.assertRedirects(response, self.user_edit_url, target_status_code=200)
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_register_redirects_extract_locale_and_app_from_next_path(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda i: user_factory(email='me@yeahoo.com')
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            response = self.client.get(
                self.url,
                {
                    'code': 'codes!!',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(b'/fr/android/')),
                        ]
                    ),
                },
            )
            self.assertRedirects(
                # Not self.user_edit_url, which would start with /en-US/firefox/
                response,
                '/fr/android/users/edit?to=/fr/android/',
                target_status_code=200,
            )
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_register_redirects_edit_absolute_to(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda i: user_factory(email='me@yeahoo.com')
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            with override_settings(DOMAIN='supersafe.com'):
                response = self.client.get(
                    self.url,
                    {
                        'code': 'codes!!',
                        'state': ':'.join(
                            [
                                self.fxa_state,
                                force_str(
                                    base64.urlsafe_b64encode(
                                        b'https://supersafe.com/go/here'
                                    )
                                ),
                            ]
                        ),
                    },
                )
            self.assertRedirects(
                response,
                self.user_edit_url + '?to=https://supersafe.com/go/here',
                target_status_code=200,
            )
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_register_redirects_edit_ignores_to_when_unsafe(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {'email': 'me@yeahoo.com', 'uid': 'e0b6f'}
        self.fxa_identify.return_value = identity, self.token_data
        self.register_user.side_effect = lambda i: user_factory(email='me@yeahoo.com')
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            response = self.client.get(
                self.url,
                {
                    'code': 'codes!!',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(b'https://go.go/here')),
                        ]
                    ),
                },
            )
            self.assertRedirects(
                response, self.user_edit_url, target_status_code=200  # No '?to=...'
            )
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert self.login_user.called
        self.register_user.assert_called_with(identity)
        assert not self.reregister_user.called

    def test_success_with_account_logs_in(self):
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com', fxa_id='10'
        )
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity, self.token_data
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            response = self.client.get(
                self.url, {'code': 'code', 'state': self.fxa_state}
            )
            self.assertRedirects(response, reverse('home'))
            assert (
                response['Cache-Control']
                == 'max-age=0, no-cache, no-store, must-revalidate, private'
            )
        self.login_user.assert_called_with(
            views.AuthenticateView, mock.ANY, user, identity, self.token_data
        )
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_banned_user_cant_log_in(self):
        UserProfile.objects.create(
            username='foobar',
            email='real@yeahoo.com',
            fxa_id='10',
            deleted=True,
            banned=datetime.now(),
        )
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity, self.token_data
        response = self.client.get(self.url, {'code': 'code', 'state': self.fxa_state})
        assert response.status_code == 403

    def test_log_in_redirects_to_next_path(self):
        user = UserProfile.objects.create(email='real@yeahoo.com', fxa_id='10')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity, self.token_data
        response = self.client.get(
            self.url,
            {
                'code': 'code',
                'state': ':'.join(
                    [
                        self.fxa_state,
                        force_str(base64.urlsafe_b64encode(b'/en-US/firefox/a/path')),
                    ]
                ),
            },
        )
        self.assertRedirects(response, '/en-US/firefox/a/path', target_status_code=404)
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        self.login_user.assert_called_with(
            views.AuthenticateView, mock.ANY, user, identity, self.token_data
        )
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_log_in_sets_fxa_data_and_redirects(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity, self.token_data
        response = self.client.get(
            self.url,
            {
                'code': 'code',
                'state': ':'.join(
                    [
                        self.fxa_state,
                        force_str(base64.urlsafe_b64encode(b'/en-US/firefox/a/path')),
                    ]
                ),
            },
        )
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        self.assertRedirects(response, '/en-US/firefox/a/path', target_status_code=404)
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )
        self.login_user.assert_called_with(
            views.AuthenticateView, mock.ANY, user, identity, self.token_data
        )
        assert not self.register_user.called
        assert not self.reregister_user.called

    def test_log_in_redirects_to_absolute_url(self):
        email = 'real@yeahoo.com'
        UserProfile.objects.create(email=email)
        self.fxa_identify.return_value = (
            {'email': email, 'uid': '9001'},
            self.token_data,
        )
        domain = 'example.org'
        next_path = f'https://{domain}/path'
        with override_settings(DOMAIN=domain):
            response = self.client.get(
                self.url,
                {
                    'code': 'code',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(next_path.encode())),
                        ]
                    ),
                },
            )
        self.assertRedirects(response, next_path, fetch_redirect_response=False)

    def test_log_in_redirects_to_code_manager(self):
        email = 'real@yeahoo.com'
        UserProfile.objects.create(email=email)
        self.fxa_identify.return_value = (
            {'email': email, 'uid': '9001'},
            self.token_data,
        )
        code_manager_url = 'https://example.org'
        next_path = f'{code_manager_url}/path'
        with override_settings(CODE_MANAGER_URL=code_manager_url):
            response = self.client.get(
                self.url,
                {
                    'code': 'code',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(next_path.encode())),
                        ]
                    ),
                },
            )
        self.assertRedirects(response, next_path, fetch_redirect_response=False)
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )

    def test_log_in_requires_https_when_request_is_secure(self):
        email = 'real@yeahoo.com'
        UserProfile.objects.create(email=email)
        self.fxa_identify.return_value = (
            {'email': email, 'uid': '9001'},
            self.token_data,
        )
        domain = 'example.org'
        next_path = f'https://{domain}/path'
        with override_settings(DOMAIN=domain):
            response = self.client.get(
                self.url,
                secure=True,
                data={
                    'code': 'code',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(next_path.encode())),
                        ]
                    ),
                },
            )
        self.assertRedirects(response, next_path, fetch_redirect_response=False)
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )

    def test_log_in_redirects_to_home_when_request_is_secure_but_next_path_is_not(
        self,
    ):  # noqa
        email = 'real@yeahoo.com'
        UserProfile.objects.create(email=email)
        self.fxa_identify.return_value = (
            {'email': email, 'uid': '9001'},
            self.token_data,
        )
        domain = 'example.org'
        next_path = f'http://{domain}/path'
        with override_settings(DOMAIN=domain):
            response = self.client.get(
                self.url,
                secure=True,
                data={
                    'code': 'code',
                    'state': ':'.join(
                        [
                            self.fxa_state,
                            force_str(base64.urlsafe_b64encode(next_path.encode())),
                        ]
                    ),
                },
            )
        with mock.patch('olympia.amo.views._frontend_view', empty_view):
            self.assertRedirects(response, reverse('home'))
        assert (
            response['Cache-Control']
            == 'max-age=0, no-cache, no-store, must-revalidate, private'
        )


class TestAuthenticateViewV3(TestAuthenticateView):
    api_version = 'v3'


class TestAccountViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory()
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.pk})
        super().setUp()

    def test_profile_url(self):
        self.client.login_api(self.user)
        response = self.client.get(reverse_ns('account-profile'))
        assert response.status_code == 200
        assert response.data['name'] == self.user.name
        assert response.data['email'] == self.user.email
        assert response.data['url'] == absolutify(self.user.get_url_path())

    def test_profile_url_404(self):
        response = self.client.get(reverse_ns('account-profile'))  # No auth.
        assert response.status_code == 401

    def test_disallowed_verbs(self):
        self.client.login_api(self.user)
        # We have no list URL to post to, try posting to accounts-profile
        # instead...
        response = self.client.post(reverse_ns('account-profile'))
        assert response.status_code == 405
        # We can try put on the detail URL though.
        response = self.client.put(self.url)
        assert response.status_code == 405

    def test_self_view(self):
        """Test that self-profile view works if you specify your pk."""
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['name'] == self.user.name
        assert response.data['email'] == self.user.email
        assert response.data['url'] == absolutify(self.user.get_url_path())

    def test_view_deleted(self):
        self.user.update(deleted=True, is_public=True)
        response = self.client.get(self.url)
        assert response.status_code == 404

        # Even as admin deleted users are not visible through the API.
        user = user_factory()
        self.grant_permission(user, 'Users:Edit')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_is_not_public_because_not_developer(self):
        assert not self.user.is_public
        response = self.client.get(self.url)  # No auth.
        assert response.status_code == 404
        # Login as a random user and check it's still not visible.
        self.client.login_api(user_factory())
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_is_public_because_developer(self):
        addon_factory(users=[self.user])
        assert self.user.is_developer and self.user.is_public
        response = self.client.get(self.url)  # No auth.
        assert response.status_code == 200
        assert response.data['name'] == self.user.name
        assert 'email' not in response.data  # Don't expose private data.
        # They are a developer so we should link to account profile url
        assert response.data['url'] == absolutify(self.user.get_url_path())

    def test_admin_view(self):
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)
        self.random_user = user_factory()
        random_user_profile_url = reverse_ns(
            'account-detail', kwargs={'pk': self.random_user.pk}
        )
        response = self.client.get(random_user_profile_url)
        assert response.status_code == 200
        assert response.data['name'] == self.random_user.name
        assert response.data['email'] == self.random_user.email
        assert response.data['url'] == absolutify(self.random_user.get_url_path())

    def test_self_view_slug(self):
        # Check it works the same with an account slug rather than pk.
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.username})
        self.test_self_view()

    def test_is_public_because_developer_slug(self):
        # Check it works the same with an account slug rather than pk.
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.username})
        self.test_is_public_because_developer()

        # Should still work if the username contains a period.
        self.user.update(username='fôo.bar')
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.username})
        self.test_is_public_because_developer()

    def test_admin_view_slug(self):
        # Check it works the same with an account slug rather than pk.
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)
        self.random_user = user_factory()
        random_user_profile_url = reverse_ns(
            'account-detail', kwargs={'pk': self.random_user.username}
        )
        response = self.client.get(random_user_profile_url)
        assert response.status_code == 200
        assert response.data['name'] == self.random_user.name
        assert response.data['email'] == self.random_user.email
        assert response.data['url'] == absolutify(self.random_user.get_url_path())


class TestProfileViewWithJWT(APIKeyAuthTestMixin, TestCase):
    """This just tests JWT Auth (external) on the profile endpoint.

    See TestAccountViewSet for internal auth test.
    """

    def test_profile_url(self):
        self.create_api_user()
        response = self.get(reverse_ns('account-profile'))
        assert response.status_code == 200
        assert response.data['name'] == self.user.name
        assert response.data['email'] == self.user.email


class TestAccountViewSetUpdate(TestCase):
    client_class = APITestClientSessionID
    update_data = {
        'display_name': 'Bob Loblaw',
        'biography': 'You don`t need double talk; you need Bob Loblaw',
        'homepage': 'http://bob-loblaw-law-web.blog',
        'location': 'law office',
        'occupation': 'lawyer',
    }

    def setUp(self):
        self.user = user_factory()
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.pk})
        super().setUp()

    def patch(self, url=None, data=None):
        return self.client.patch(url or self.url, data or self.update_data)

    def test_basic_patch(self):
        self.client.login_api(self.user)
        original = self.client.get(self.url).content
        response = self.patch()
        assert response.status_code == 200
        assert response.content != original
        modified_json = json.loads(force_str(response.content))
        self.user = self.user.reload()
        for prop, value in self.update_data.items():
            assert modified_json[prop] == value
            assert getattr(self.user, prop) == value

    def test_no_auth(self):
        response = self.patch()
        assert response.status_code == 401

    def test_different_account(self):
        self.client.login_api(self.user)
        url = reverse_ns('account-detail', kwargs={'pk': user_factory().pk})
        response = self.patch(url=url)
        assert response.status_code == 403

    def test_admin_patch(self):
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        url = reverse_ns('account-detail', kwargs={'pk': random_user.pk})
        original = self.client.get(url).content
        response = self.patch(url=url)
        assert response.status_code == 200
        assert response.content != original
        modified_json = json.loads(force_str(response.content))
        random_user = random_user.reload()
        for prop, value in self.update_data.items():
            assert modified_json[prop] == value
            assert getattr(random_user, prop) == value

    def test_read_only_fields(self):
        self.client.login_api(self.user)
        existing_username = self.user.username
        original = self.client.get(self.url).content
        # Try to patch a field that can't be patched.
        response = self.patch(
            data={'last_login_ip': '666.666.666.666', 'username': 'new_username'}
        )
        assert response.status_code == 200
        assert response.content == original
        self.user = self.user.reload()
        # Confirm field hasn't been updated.
        response = json.loads(force_str(response.content))
        assert response['last_login_ip'] == '127.0.0.1'
        assert self.user.last_login_ip == '127.0.0.1'
        assert response['username'] == existing_username
        assert self.user.username == existing_username

    def test_biography_no_links(self):
        self.client.login_api(self.user)
        response = self.patch(
            data={'biography': '<a href="https://google.com">google</a>'}
        )
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'biography': ['No links are allowed.']
        }

    def test_biography_too_long(self):
        self.client.login_api(self.user)
        response = self.patch(data={'biography': 'ä' * 256})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'biography': ['Ensure this field has no more than 255 characters.']
        }

    def test_display_name_validation(self):
        self.client.login_api(self.user)
        response = self.patch(data={'display_name': 'a'})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'display_name': ['Ensure this field has at least 2 characters.']
        }

        response = self.patch(data={'display_name': 'a' * 51})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'display_name': ['Ensure this field has no more than 50 characters.']
        }

        response = self.patch(data={'display_name': '\x7F\u20DF'})
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'display_name': ['Must contain at least one printable character.']
        }

        response = self.patch(data={'display_name': 'a\x7F'})
        assert response.status_code == 200

        response = self.patch(data={'display_name': 'a' * 50})
        assert response.status_code == 200

    def test_picture_upload(self):
        # Make sure the picture doesn't exist already or we get a false-postive
        assert not path.exists(self.user.picture_path)

        self.client.login_api(self.user)
        photo = get_uploaded_file('transparent.png')
        data = {'picture_upload': photo, 'biography': 'not just setting photo'}
        response = self.client.patch(self.url, data, format='multipart')
        assert response.status_code == 200
        json_content = json.loads(force_str(response.content))
        self.user = self.user.reload()
        assert 'anon_user.png' not in json_content['picture_url']
        assert '%s.png' % self.user.id in json_content['picture_url']
        assert self.user.biography == 'not just setting photo'

        assert path.exists(self.user.picture_path)

    def test_delete_picture(self):
        # use test_picture_upload to set up a photo
        self.test_picture_upload()
        assert path.exists(self.user.picture_path)
        # call the endpoint to delete
        picture_url = reverse_ns('account-picture', kwargs={'pk': self.user.pk})
        response = self.client.delete(picture_url)
        assert response.status_code == 200
        # Should delete the photo
        assert not path.exists(self.user.picture_path)
        json_content = json.loads(force_str(response.content))
        assert json_content['picture_url'] is None

    def test_account_picture_disallowed_verbs(self):
        picture_url = reverse_ns('account-picture', kwargs={'pk': self.user.pk})
        self.client.login_api(self.user)
        response = self.client.get(picture_url)
        assert response.status_code == 405
        response = self.client.post(picture_url)
        assert response.status_code == 405
        response = self.client.put(picture_url)
        assert response.status_code == 405
        response = self.client.patch(picture_url)
        assert response.status_code == 405

    def test_picture_upload_wrong_format(self):
        self.client.login_api(self.user)
        gif = get_uploaded_file('animated.gif')
        data = {'picture_upload': gif}
        response = self.client.patch(self.url, data, format='multipart')
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'picture_upload': ['Images must be either PNG or JPG.']
        }

    def test_picture_upload_animated(self):
        self.client.login_api(self.user)
        gif = get_uploaded_file('animated.png')
        data = {'picture_upload': gif}
        response = self.client.patch(self.url, data, format='multipart')
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'picture_upload': ['Images cannot be animated.']
        }

    def test_picture_upload_not_image(self):
        self.client.login_api(self.user)
        gif = get_uploaded_file('non-image.png')
        data = {'picture_upload': gif}
        response = self.client.patch(self.url, data, format='multipart')
        assert response.status_code == 400
        assert json.loads(force_str(response.content)) == {
            'picture_upload': [
                'Upload a valid image. The file you uploaded was either not '
                'an image or a corrupted image.'
            ]
        }


class TestAccountViewSetDelete(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory()
        self.url = reverse_ns('account-detail', kwargs={'pk': self.user.pk})
        super().setUp()

    def test_delete(self):
        self.client.login_api(self.user)
        # Also add api token and session cookies: they should be cleared when
        # the user deletes their own account.
        self.client.cookies[settings.SESSION_COOKIE_NAME] = 'something'
        # Also add cookies that should be kept.
        self.client.cookies['dontremoveme'] = 'keepme'
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert response.cookies[settings.SESSION_COOKIE_NAME].value == ''
        assert (
            response.cookies[settings.SESSION_COOKIE_NAME].get('samesite')
            == settings.SESSION_COOKIE_SAMESITE
        )
        assert response['Cache-Control'] == 's-maxage=0'
        assert 'dontremoveme' not in response.cookies
        assert self.client.cookies[settings.SESSION_COOKIE_NAME].value == ''
        assert self.client.cookies['dontremoveme'].value == 'keepme'
        assert self.user.reload().deleted
        alog = ActivityLog.objects.get(user=self.user, action=amo.LOG.USER_DELETED.id)
        assert alog.arguments == [self.user]

    def test_no_auth(self):
        response = self.client.delete(self.url)
        assert response.status_code == 401

    def test_different_account(self):
        self.client.login_api(self.user)
        url = reverse_ns('account-detail', kwargs={'pk': user_factory().pk})
        response = self.client.delete(url)
        assert response.status_code == 403

    def test_admin_delete(self):
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)

        random_user = user_factory()
        url = reverse_ns('account-detail', kwargs={'pk': random_user.pk})
        response = self.client.delete(url)
        assert response.status_code == 204
        assert random_user.reload().deleted
        alog = ActivityLog.objects.get(user=self.user, action=amo.LOG.USER_DELETED.id)
        assert alog.arguments == [random_user]

    def test_developers_can_delete(self):
        self.client.login_api(self.user)
        addon = addon_factory(users=[self.user])
        assert self.user.is_developer and self.user.is_addon_developer

        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert self.user.reload().deleted
        assert addon.reload().is_deleted

    def test_theme_developers_can_delete(self):
        self.client.login_api(self.user)
        addon = addon_factory(users=[self.user], type=amo.ADDON_STATICTHEME)
        assert self.user.is_developer and self.user.is_artist

        response = self.client.delete(self.url)
        assert addon.reload().is_deleted
        assert response.status_code == 204
        assert self.user.reload().deleted


class TestAccountSuperCreate(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        create_switch('super-create-accounts', active=True)
        self.create_api_user()
        self.url = reverse_ns('accounts.super-create')
        group = Group.objects.create(
            name='Account Super Creators', rules='Accounts:SuperCreate'
        )
        GroupUser.objects.create(group=group, user=self.user)

    def test_require_auth(self):
        self.auth_required(views.AccountSuperCreate)

    def test_require_a_waffle_switch(self):
        Switch.objects.all().delete()
        res = self.post(self.url, {})
        assert res.status_code == 404, res.content

    def test_requesting_user_must_have_access(self):
        GroupUser.objects.filter(user=self.user).delete()
        res = self.post(self.url, {})
        assert res.status_code == 403, res.content
        assert res.data['detail'] == (
            'You do not have permission to perform this action.'
        )

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
            'username': ['Someone with this username already exists in the system'],
        }

    def test_cannot_add_user_to_group_when_one_doesnt_exist(self):
        res = self.post(self.url, {'group': 'reviewer'})
        assert res.status_code == 422, res.content
        assert res.data['errors'] == {
            'group': [
                'Could not find a permissions group with the exact rules needed.'
            ],
        }

    def test_can_create_a_reviewer_user(self):
        Group.objects.create(rules='Addons:Review', name='reviewer group')
        res = self.post(self.url, {'group': 'reviewer'})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert action_allowed_for(user, amo.permissions.ADDONS_REVIEW)

    def test_can_create_an_admin_user(self):
        group = Group.objects.create(rules='*:*', name='admin group')
        res = self.post(self.url, {'group': 'admin'})

        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert action_allowed_for(user, amo.permissions.NONE)
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
            '/en-US/firefox/addon/dęlîcíøùs-päñčåkę/?src=hp-dl-featured'
        )

    def test_path_with_unicodedecodeerror(self):
        parts = [
            '09aedd38eebd72e896250ae5b7ea9c0172542b6cec7683e58227e5670df12fb2',
            'l2vulvvtl2rldmvsb3blcnmv',
        ]
        next_path = views.parse_next_path(parts)
        assert next_path is None


class TestSessionView(TestCase):
    api_version = 'auth'
    token_data = {
        'id_token': 'someopenidtoken',
        'access_token': 'someaccesstoken',
        'refresh_token': 'somerefresh_token',
        'expires_in': 12345,
        'access_token_expiry': time.time() + 12345,
    }

    def login_user(self, user):
        identity = {
            'username': user.username,
            'email': user.email,
            'uid': user.fxa_id,
        }
        self.initialize_session({'fxa_state': 'myfxastate'})
        with mock.patch(
            'olympia.accounts.views.verify.fxa_identify',
            lambda code, config: (identity, self.token_data),
        ):
            self.client.get(
                '{url}?code={code}&state={state}'.format(
                    url=reverse_ns(
                        'accounts.authenticate', api_version=self.api_version
                    ),
                    state='myfxastate',
                    code='thecode',
                )
            )
            assert self.client.session['_auth_user_id'] == str(user.id)

    def test_delete_when_authenticated(self):
        user = user_factory(fxa_id='123123412')
        self.login_user(user)
        authorization = f'Session {self.client.session.session_key}'
        assert user.auth_id
        response = self.client.delete(
            reverse_ns('accounts.session'), HTTP_AUTHORIZATION=authorization
        )
        assert response.status_code == 200, response.content
        assert not self.client.session.get('_auth_user_id')
        user.reload()
        assert not user.auth_id  # Cleared at logout.

    def test_delete_when_unauthenticated(self):
        response = self.client.delete(reverse_ns('accounts.session'))
        assert response.status_code == 401

    def test_cors_headers_are_exposed(self):
        user = user_factory(fxa_id='123123412')
        self.login_user(user)
        authorization = f'Session {self.client.session.session_key}'
        origin = 'http://example.org'
        response = self.client.delete(
            reverse_ns('accounts.session'),
            HTTP_AUTHORIZATION=authorization,
            HTTP_ORIGIN=origin,
        )
        assert response.status_code == 200, response.content
        assert response['Access-Control-Allow-Origin'] == origin
        assert response['Access-Control-Allow-Credentials'] == 'true'

    def test_delete_omits_cors_headers_when_there_is_no_origin(self):
        user = user_factory(fxa_id='123123412')
        self.login_user(user)
        authorization = f'Session {self.client.session.session_key}'
        response = self.client.delete(
            reverse_ns('accounts.session'),
            HTTP_AUTHORIZATION=authorization,
        )
        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Allow-Credentials')

    def test_responds_to_cors_preflight_requests(self):
        origin = 'http://example.org'
        response = self.client.options(
            reverse_ns('accounts.session'),
            HTTP_ORIGIN=origin,
        )
        assert response['Content-Length'] == '0'
        assert response['Access-Control-Allow-Credentials'] == 'true'
        assert response.has_header('Access-Control-Allow-Headers')
        assert response.has_header('Access-Control-Allow-Methods')
        assert 'DELETE' in response['Access-Control-Allow-Methods']
        assert response.has_header('Access-Control-Max-Age')
        assert response['Access-Control-Allow-Origin'] == origin

    def test_options_omits_cors_headers_when_there_is_no_origin(self):
        response = self.client.options(reverse_ns('accounts.session'))
        assert not response.has_header('Access-Control-Allow-Credentials')
        assert not response.has_header('Access-Control-Allow-Headers')
        assert not response.has_header('Access-Control-Allow-Methods')
        assert not response.has_header('Access-Control-Allow-Origin')
        assert not response.has_header('Access-Control-Max-Age')


class TestSessionViewV3(TestSessionView):
    api_version = 'v3'


class TestAccountNotificationViewSetList(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory()
        addon_factory(users=[self.user])  # Developers get all notifications.
        self.url = reverse_ns('notification-list', kwargs={'user_pk': self.user.pk})
        super().setUp()

    def test_defaults_only(self):
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 8
        assert {'name': 'reply', 'enabled': True, 'mandatory': False} in response.data

    def test_defaults_non_dev(self):
        self.user.addons.all().delete()
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 2
        assert {'name': 'reply', 'enabled': True, 'mandatory': False} in response.data

    def test_user_set_notifications_included(self):
        reply_notification = NOTIFICATIONS_BY_ID[3]
        UserNotification.objects.create(
            user=self.user, notification_id=reply_notification.id, enabled=False
        )
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 8
        assert {'name': 'reply', 'enabled': False, 'mandatory': False} in response.data

    def test_user_set_notifications_included_non_dev(self):
        self.user.addons.all().delete()
        reply_notification = NOTIFICATIONS_BY_ID[3]
        UserNotification.objects.create(
            user=self.user, notification_id=reply_notification.id, enabled=False
        )
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 2
        assert {'name': 'reply', 'enabled': False, 'mandatory': False} in response.data

    def test_old_notifications_are_safely_ignored(self):
        UserNotification.objects.create(
            user=self.user, notification_id=69, enabled=True
        )
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 8
        # Check for any known notification, just to see the response looks okay
        assert {'name': 'reply', 'enabled': True, 'mandatory': False} in response.data

    def test_basket_integration(self):
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

        with mock.patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok',
                'token': '123',
                'newsletters': ['about-addons'],
            }

            response = self.client.get(self.url)

        assert response.status_code == 200
        assert {
            'name': 'announcements',
            'enabled': True,
            'mandatory': False,
        } in response.data

    def test_basket_integration_non_dev(self):
        self.user.addons.all().delete()
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

        with mock.patch('basket.base.request', autospec=True) as request_call:
            response = self.client.get(self.url)
            # Basket is a dev-only notification so it shouldn't be called.
            assert not request_call.called

        assert response.status_code == 200
        # And the notification shoudn't be included either.
        assert {
            'name': 'announcements',
            'enabled': True,
            'mandatory': False,
        } not in response.data

    def test_basket_integration_ignore_db(self):
        # Add some old obsolete data in the database for a notification that
        # is handled by basket: it should be ignored.
        notification_id = REMOTE_NOTIFICATIONS_BY_BASKET_ID['about-addons'].id
        UserNotification.objects.create(
            user=self.user, notification_id=notification_id, enabled=True
        )

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

        with mock.patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok',
                'token': '123',
                'newsletters': ['garbage'],
            }

            response = self.client.get(self.url)

        assert response.status_code == 200
        assert {
            'name': 'announcements',
            'enabled': False,
            'mandatory': False,
        } in response.data
        # Check our response only contains one announcements notification.
        assert (
            len([nfn for nfn in response.data if nfn['name'] == 'announcements']) == 1
        )

    def test_no_auth_fails(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_different_account_fails(self):
        self.user = user_factory()  # different user now
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_admin_view(self):
        self.user = user_factory()  # different user now
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data) == 8

    def test_disallowed_verbs(self):
        self.client.login_api(self.user)
        response = self.client.put(self.url)
        assert response.status_code == 405
        response = self.client.patch(self.url)
        assert response.status_code == 405
        response = self.client.delete(self.url)
        assert response.status_code == 405


class TestAccountNotificationViewSetUpdate(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory()
        addon_factory(users=[self.user])  # Developers get all notifications.
        self.url = reverse_ns('notification-list', kwargs={'user_pk': self.user.pk})
        self.list_url = reverse_ns(
            'notification-list', kwargs={'user_pk': self.user.pk}
        )
        super().setUp()

    def test_new_notification(self):
        reply_notification = NOTIFICATIONS_BY_ID[3]
        assert not UserNotification.objects.filter(
            user=self.user, notification_id=reply_notification.id
        ).exists()
        self.client.login_api(self.user)
        # Check it's set to the default True beforehand.
        assert {
            'name': 'reply',
            'enabled': True,
            'mandatory': False,
        } in self.client.get(self.list_url).data

        response = self.client.post(self.url, data={'reply': False})
        assert response.status_code == 200, response.content
        # Now we've set it to False.
        assert {'name': 'reply', 'enabled': False, 'mandatory': False} in response.data
        # And the notification has been saved.
        un_obj = UserNotification.objects.get(
            user=self.user, notification_id=reply_notification.id
        )
        assert not un_obj.enabled

    def test_updated_notification(self):
        reply_notification = NOTIFICATIONS_BY_ID[3]
        # Create the UserNotification object
        UserNotification.objects.create(
            user=self.user, notification_id=reply_notification.id, enabled=True
        )
        self.client.login_api(self.user)

        response = self.client.post(self.url, data={'reply': False})
        assert response.status_code == 200, response.content
        # Now we've set it to False.
        assert {'name': 'reply', 'enabled': False, 'mandatory': False} in response.data
        # And the notification has been saved.
        un_obj = UserNotification.objects.get(
            user=self.user, notification_id=reply_notification.id
        )
        assert not un_obj.enabled

    def test_set_mandatory_fail(self):
        contact_notification = NOTIFICATIONS_BY_ID[12]
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'individual_contact': False})
        assert response.status_code == 400
        # Attempt fails.
        assert b'Attempting to set [individual_contact] to False.' in (response.content)
        # And the notification hasn't been saved.
        assert not UserNotification.objects.filter(
            user=self.user, notification_id=contact_notification.id
        ).exists()

    def test_no_auth_fails(self):
        response = self.client.post(self.url, data={'dev_thanks': False})
        assert response.status_code == 401

    def test_different_account_fails(self):
        self.user = user_factory()  # different user now
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'dev_thanks': False})
        assert response.status_code == 403

    def test_admin_update(self):
        original_user = self.user
        self.user = user_factory()  # different user now
        self.grant_permission(self.user, 'Users:Edit')
        self.client.login_api(self.user)

        response = self.client.post(self.url, data={'reply': False})
        assert response.status_code == 200, response.content
        # Now we've set it to False.
        assert {'name': 'reply', 'enabled': False, 'mandatory': False} in response.data
        # And the notification has been saved.
        un_obj = UserNotification.objects.get(
            user=original_user, notification_id=NOTIFICATIONS_BY_ID[3].id
        )
        assert not un_obj.enabled

    def test_basket_integration(self):
        self.client.login_api(self.user)

        assert {
            'name': 'announcements',
            'enabled': False,
            'mandatory': False,
        } in self.client.get(self.list_url).data

        with mock.patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok',
                'token': '123',
                'newsletters': ['announcements'],
            }
            self.client.post(self.url, data={'announcements': True})

        request_call.assert_called_with(
            'post',
            'subscribe',
            data={
                'newsletters': 'about-addons',
                'sync': 'Y',
                'optin': 'Y',
                'source_url': (
                    'http://testserver/api/{api_version}/accounts/account/'
                    '{id}/notifications/'
                ).format(id=self.user.id, api_version=api_settings.DEFAULT_VERSION),
                'email': self.user.email,
            },
            headers={'x-api-key': 'testkey'},
        )

        with mock.patch('basket.base.request', autospec=True) as request_call:
            request_call.return_value = {
                'status': 'ok',
                'token': '123',
                'newsletters': [],
            }
            self.client.post(self.url, data={'announcements': False})

        request_call.assert_called_with(
            'post',
            'unsubscribe',
            data={'newsletters': 'about-addons', 'email': self.user.email},
            token='123',
        )


class TestAccountNotificationUnsubscribe(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.user = user_factory()
        self.url = reverse_ns('account-unsubscribe')
        super().setUp()

    def test_unsubscribe_user(self):
        notification_const = NOTIFICATIONS_COMBINED[0]
        UserNotification.objects.create(
            user=self.user, notification_id=notification_const.id, enabled=True
        )
        token, hash_ = UnsubscribeCode.create(self.user.email)
        data = {'token': token, 'hash': hash_, 'notification': notification_const.short}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200, response.content
        assert response.data == {'name': 'reply', 'enabled': False, 'mandatory': False}
        ntn = UserNotification.objects.get(
            user=self.user, notification_id=notification_const.id
        )
        assert not ntn.enabled

        ntn.delete()
        assert not UserNotification.objects.filter(
            user=self.user, notification_id=notification_const.id
        ).exists()
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200
        assert UserNotification.objects.filter(
            user=self.user, notification_id=notification_const.id, enabled=False
        ).exists()

    def test_unsubscribe_dev_notification(self):
        # Even if the user if not currently a developer they should be able to
        # unsubscribe from the emails if they have the link.
        assert not self.user.is_developer

        notification_const = NOTIFICATIONS_BY_ID[7]
        assert notification_const.group == 'dev'
        assert not UserNotification.objects.filter(
            user=self.user, notification_id=notification_const.id
        ).exists()

        token, hash_ = UnsubscribeCode.create(self.user.email)
        data = {'token': token, 'hash': hash_, 'notification': notification_const.short}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200, response.content
        assert response.data == {
            'name': 'new_review',
            'enabled': False,
            'mandatory': False,
        }
        ntn = UserNotification.objects.get(
            user=self.user, notification_id=notification_const.id
        )
        assert not ntn.enabled

    def test_unsubscribe_invalid_notification(self):
        token, hash_ = UnsubscribeCode.create(self.user.email)
        data = {'token': token, 'hash': hash_, 'notification': 'foobaa'}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 400
        assert response.content == b'["Notification [foobaa] does not exist"]'

    def test_unsubscribe_invalid_token_or_hash(self):
        token, hash_ = UnsubscribeCode.create(self.user.email)
        data = {'token': token, 'hash': hash_ + 'a', 'notification': 'reply'}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 403
        assert response.data == {'detail': 'Invalid token or hash.'}

        data = {'token': b'a' + token, 'hash': hash_, 'notification': 'reply'}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 403
        assert response.data == {'detail': 'Invalid token or hash.'}

    def test_email_doesnt_exist(self):
        token, hash_ = UnsubscribeCode.create('email@not-an-amo-user.com')
        data = {'token': token, 'hash': hash_, 'notification': 'reply'}
        response = self.client.post(self.url, data=data)
        assert response.status_code == 403
        assert response.data == {'detail': 'Email address not found.'}


class TestFxaNotificationView(TestCase):
    FXA_ID = 'ABCDEF012345689'
    FXA_EVENT = {
        'iss': 'https://accounts.firefox.com/',
        'sub': FXA_ID,
        'aud': 'REMOTE_SYSTEM',
        'iat': 1565720808,
        'jti': 'e19ed6c5-4816-4171-aa43-56ffe80dbda1',
        'events': {
            'https://schemas.accounts.firefox.com/event/profile-change': {
                'email': 'example@mozilla.com'
            }
        },
    }
    JWKS_RESPONSE = {
        'keys': [
            {
                'kty': 'RSA',
                'alg': 'RS256',
                'kid': '20190730-15e473fd',
                'fxa-createdAt': 1564502400,
                'use': 'sig',
                'n': '15OpVGC7ws_SlU0gRbRh1Iwo8_gR8ElX2CDnbN5blKyXLg-ll0ogktoDXc-tDvTab'
                'RTxi7AXU0wWQ247odhHT47y5uz0GASYXdfPponynQ_xR9CpNn1eEL1gvDhQN9rfPIzfncl'
                '8FUi9V4WMd5f600QC81yDw9dX-Z8gdkru0aDaoEKF9-wU2TqrCNcQdiJCX9BISotjz_9cm'
                'GwKXFEekQNJWBeRQxH2bUmgwUK0HaqwW9WbYOs-zstNXXWFsgK9fbDQqQeGehXLZM4Cy5M'
                'gl_iuSvnT3rLzPo2BmlxMLUvRqBx3_v8BTtwmNGA0v9O0FJS_mnDq0Iue0Dz8BssQCQ',
                'e': 'AQAB',
            }
        ]
    }

    def test_get_fxa_verifying_keys(self):
        responses.add(
            responses.GET,
            f'{settings.FXA_OAUTH_HOST}/jwks',
            json=self.JWKS_RESPONSE,
        )
        responses.add(
            responses.GET,
            f'{settings.FXA_OAUTH_HOST}/jwks',
            json={},
        )
        assert (
            FxaNotificationView().get_fxa_verifying_keys() == self.JWKS_RESPONSE['keys']
        )
        # the call is cached on cls.fxa_verifiying_keys after the first call
        assert (
            FxaNotificationView().get_fxa_verifying_keys() == self.JWKS_RESPONSE['keys']
        )
        del FxaNotificationView.fxa_verifying_keys
        with self.assertRaises(exceptions.AuthenticationFailed):
            FxaNotificationView().get_fxa_verifying_keys()

    @mock.patch('olympia.accounts.views.jwt.decode')
    def test_get_jwt_payload(self, decode_mock):
        FxaNotificationView.fxa_verifying_keys = [
            {'kty': 'RSA', 'alg': 'fooo'},  # should be ignored
            *self.JWKS_RESPONSE['keys'],
        ]
        decode_mock.return_value = self.FXA_EVENT
        request_factory = APIRequestFactory()

        authd_jwt = FxaNotificationView().get_jwt_payload(
            request_factory.get('/', HTTP_AUTHORIZATION='Bearer fooo')
        )
        assert authd_jwt == self.FXA_EVENT

        # check a malformed bearer header is handled
        with self.assertRaises(exceptions.AuthenticationFailed):
            FxaNotificationView().get_jwt_payload(
                request_factory.get('/', HTTP_AUTHORIZATION='Bearer ')
            )

        with self.assertRaises(exceptions.AuthenticationFailed):
            FxaNotificationView().get_jwt_payload(
                request_factory.get('/', HTTP_AUTHORIZATION='Fooo')
            )

        with self.assertRaises(exceptions.AuthenticationFailed):
            FxaNotificationView().get_jwt_payload(
                request_factory.get('/', HTTP_AUTHORIZATION='Bearer baa Bearer ')
            )

        # check decode exceptions are caught
        decode_mock.side_effect = jwt.exceptions.PyJWTError()
        with self.assertRaises(exceptions.AuthenticationFailed):
            FxaNotificationView().get_jwt_payload(
                request_factory.get('/', HTTP_AUTHORIZATION='Bearer fooo')
            )

    def test_post(self):
        url = reverse_ns('fxa-notification', api_version='auth')
        class_path = (
            f'{FxaNotificationView.__module__}.' f'{FxaNotificationView.__name__}'
        )
        with (
            mock.patch(f'{class_path}.get_jwt_payload') as get_jwt_mock,
            mock.patch(f'{class_path}.process_event') as process_event_mock,
            freezegun.freeze_time(),
        ):
            get_jwt_mock.return_value = self.FXA_EVENT
            response = self.client.post(url)
            process_event_mock.assert_called_with(
                self.FXA_ID,
                FxaNotificationView.FXA_PROFILE_CHANGE_EVENT,
                {'email': 'example@mozilla.com'},
            )
        assert response.status_code == 202

    @mock.patch('olympia.accounts.views.primary_email_change_event.delay')
    def test_process_event_email_change(self, event_mock):
        with freezegun.freeze_time():
            FxaNotificationView().process_event(
                self.FXA_ID,
                FxaNotificationView.FXA_PROFILE_CHANGE_EVENT,
                {'email': 'new-email@example.com'},
            )
            event_mock.assert_called_with(
                self.FXA_ID, datetime.now().timestamp(), 'new-email@example.com'
            )

    def test_process_event_email_change_integration(self):
        user = user_factory(
            email='old-email@example.com',
            fxa_id=self.FXA_ID,
            email_changed=datetime(2017, 10, 11),
        )
        with freezegun.freeze_time():
            FxaNotificationView().process_event(
                self.FXA_ID,
                FxaNotificationView.FXA_PROFILE_CHANGE_EVENT,
                {'email': 'new-email@example.com'},
            )
            now = datetime.now()
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == now

    @mock.patch('olympia.accounts.views.delete_user_event.delay')
    def test_process_event_delete(self, event_mock):
        with freezegun.freeze_time():
            FxaNotificationView().process_event(
                self.FXA_ID,
                FxaNotificationView.FXA_DELETE_EVENT,
                {},
            )
            event_mock.assert_called_with(self.FXA_ID, datetime.now().timestamp())

    @override_switch('fxa-account-delete', active=True)
    def test_process_event_delete_integration(self):
        user = user_factory(fxa_id=self.FXA_ID)
        FxaNotificationView().process_event(
            self.FXA_ID,
            FxaNotificationView.FXA_DELETE_EVENT,
            {},
        )
        user.reload()
        assert user.email is not None
        assert user.deleted
        assert user.fxa_id is not None

    @mock.patch('olympia.accounts.views.clear_sessions_event.delay')
    def test_process_event_password_change(self, event_mock):
        FxaNotificationView().process_event(
            self.FXA_ID,
            FxaNotificationView.FXA_PASSWORDCHANGE_EVENT,
            {'changeTime': 1565721242227},
        )
        event_mock.assert_called_with(self.FXA_ID, 1565721242.227, 'password-change')

    def test_process_event_password_change_integration(self):
        user = user_factory(fxa_id=self.FXA_ID)
        FxaNotificationView().process_event(
            self.FXA_ID,
            FxaNotificationView.FXA_PASSWORDCHANGE_EVENT,
            {},
        )
        user.reload()
        assert user.auth_id is None
