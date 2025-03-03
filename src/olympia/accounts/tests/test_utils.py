from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

from olympia.accounts import utils
from olympia.amo.tests import TestCase


FXA_CONFIG = {
    'other': {'client_id': 'foo_other', 'client_secret': 'bar_other'},
}


@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_without_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
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
        'client_id': ['amodefault'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
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
        'client_id': ['amodefault'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_token():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
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
        'client_id': ['amodefault'],
        'id_token_hint': ['YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo='],
        'prompt': ['none'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_request():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
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
        'client_id': ['amodefault'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_login_hint():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        enforce_2fa=True,
        request=request,
        login_hint='test@example.com',
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
        'client_id': ['amodefault'],
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
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=utils.path_with_query(request),
    )
    state = parse_qs(urlparse(url).query)['state'][0]
    next_path = urlsafe_b64decode(state.split(':')[1] + '===')
    assert next_path.decode('utf-8') == path


def test_redirect_for_login():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login(request)
    assert response['location'] == utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
    )
    assert request.session['enforce_2fa'] is False


def test_redirect_for_login_with_next_path():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login(request, next_path='/over/the/rainbow')
    assert response['location'] == utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/over/the/rainbow',
    )
    assert request.session['enforce_2fa'] is False


def test_redirect_for_login_with_config():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login(request, config=FXA_CONFIG['other'])
    assert response['location'] == utils.fxa_login_url(
        config=FXA_CONFIG['other'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
    )
    assert request.session['enforce_2fa'] is False


def test_redirect_for_login_with_2fa_enforced():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login_with_2fa_enforced(request)
    assert response['location'] == utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
        enforce_2fa=True,
    )
    assert request.session['enforce_2fa'] is True


def test_redirect_for_login_with_2fa_enforced_id_token_hint():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login_with_2fa_enforced(
        request, id_token_hint='some_token_hint'
    )
    assert response['location'] == utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
        enforce_2fa=True,
        id_token_hint='some_token_hint',
    )
    assert request.session['enforce_2fa'] is True


def test_redirect_for_login_with_2fa_enforced_and_next_path():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login_with_2fa_enforced(
        request, next_path='/over/the/rainbow'
    )
    assert response['location'] == utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/over/the/rainbow',
        enforce_2fa=True,
    )
    assert request.session['enforce_2fa'] is True


def test_redirect_for_login_with_2fa_enforced_and_config():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login_with_2fa_enforced(
        request, config=FXA_CONFIG['other']
    )
    assert response['location'] == utils.fxa_login_url(
        config=FXA_CONFIG['other'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
        enforce_2fa=True,
    )
    assert request.session['enforce_2fa'] is True


@override_settings(FXA_CONFIG={'default': {'client_id': '.'}})
def test_fxa_login_url_when_faking_fxa_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    raw_url = utils.fxa_login_url(
        config=settings.FXA_CONFIG['default'],
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
        'client_id': ['.'],
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
class TestGetFxaConfigAndName(TestCase):
    def test_no_config(self):
        request = RequestFactory().get('/login')
        assert utils.get_fxa_config_name(request) == 'baz'
        config = utils.get_fxa_config(request)
        assert config == {'BAZ': 789}

    def test_config_alternate(self):
        request = RequestFactory().get('/login?config=bar')
        assert utils.get_fxa_config_name(request) == 'bar'
        config = utils.get_fxa_config(request)
        assert config == {'BAR': 456}

    def test_config_is_default(self):
        request = RequestFactory().get('/login?config=baz')
        assert utils.get_fxa_config_name(request) == 'baz'
        config = utils.get_fxa_config(request)
        assert config == {'BAZ': 789}
