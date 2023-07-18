from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import parse_qs, urlparse
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

from olympia.accounts import utils
from olympia.amo.tests import TestCase


FXA_CONFIG = {
    'default': {
        'client_id': 'foo',
        'client_secret': 'bar',
    },
}


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_without_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=False,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_token():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
        id_token_hint='YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo=',
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'client_id': ['foo'],
        'id_token_hint': ['YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo='],
        'prompt': ['none'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_nothing():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_nothing_with_anonymous_user():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    request.user = AnonymousUser()

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
        request=request,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_login_hint():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    request.user = mock.Mock(is_authenticated=True, email='test@example.com')

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
        request=request,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'client_id': ['foo'],
        'login_hint': ['test@example.com'],
        'prompt': ['none'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


def test_unicode_next_path():
    path = '/en-US/føø/bãr'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'fake-state'}
    url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=utils.path_with_query(request),
    )
    state = parse_qs(urlparse(url).query)['state'][0]
    next_path = urlsafe_b64decode(state.split(':')[1] + '===')
    assert next_path.decode('utf-8') == path


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_redirect_for_login():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login(request)
    assert response['location'] == utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
    )


@override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=True)
def test_fxa_login_url_when_faking_fxa_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
    )
    url = urlparse(raw_url)
    assert url.scheme == ''
    assert url.netloc == ''
    assert url.path == reverse('fake-fxa-authorization')
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(
    FXA_CONFIG={
        'foo': {'FOO': 123},
        'bar': {'BAR': 456},
        'baz': {'BAZ': 789},
    },
    DEFAULT_FXA_CONFIG_NAME='baz',
)
class TestGetFxaConfig(TestCase):
    def test_no_config(self):
        request = RequestFactory().get('/login')
        config = utils.get_fxa_config(request)
        assert config == {'BAZ': 789}

    def test_config_alternate(self):
        request = RequestFactory().get('/login?config=bar')
        config = utils.get_fxa_config(request)
        assert config == {'BAR': 456}

    def test_config_is_default(self):
        request = RequestFactory().get('/login?config=baz')
        config = utils.get_fxa_config(request)
        assert config == {'BAZ': 789}
