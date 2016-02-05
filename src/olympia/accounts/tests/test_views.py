import base64

from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.urlresolvers import resolve, reverse
from django.test import TestCase
from django.test.utils import override_settings

import mock

from rest_framework.test import APIRequestFactory, APITestCase

from olympia.accounts import verify, views
from olympia.amo.helpers import absolutify, urlparams
from olympia.amo.tests import (
    assert_url_equal, create_switch, InitializeSessionMixin)
from olympia.api.tests.utils import APIAuthTestCase
from olympia.users.models import UserProfile

FXA_CONFIG = {'some': 'stuff', 'that is': 'needed'}


class TestFxALoginWaffle(APITestCase):

    def setUp(self):
        self.login_url = reverse('accounts.login')
        self.register_url = reverse('accounts.register')
        self.source_url = reverse('accounts.source')

    def test_login_404_when_waffle_is_off(self):
        create_switch('fxa-auth', active=False)
        response = self.client.post(self.login_url)
        assert response.status_code == 404

    def test_login_422_when_waffle_is_on(self):
        create_switch('fxa-auth', active=True)
        response = self.client.post(self.login_url)
        assert response.status_code == 422

    def test_register_404_when_waffle_is_off(self):
        create_switch('fxa-auth', active=False)
        response = self.client.post(self.register_url)
        assert response.status_code == 404

    def test_register_422_when_waffle_is_on(self):
        create_switch('fxa-auth', active=True)
        response = self.client.post(self.register_url)
        assert response.status_code == 422

    def test_source_404_when_waffle_is_off(self):
        create_switch('fxa-auth', active=False)
        response = self.client.get(self.source_url)
        assert response.status_code == 404

    def test_source_200_when_waffle_is_on(self):
        create_switch('fxa-auth', active=True)
        response = self.client.get(self.source_url)
        assert response.status_code == 200


class TestLoginUser(TestCase):

    def setUp(self):
        self.request = APIRequestFactory().get('/login')
        setattr(self.request, 'session', 'session')
        messages = FallbackStorage(self.request)
        setattr(self.request, '_messages', messages)
        self.user = UserProfile.objects.create(
            email='real@yeahoo.com', fxa_id='9001')
        self.identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        patcher = mock.patch('olympia.accounts.views.login')
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_user_gets_logged_in(self):
        assert len(get_messages(self.request)) == 0
        views.login_user(self.request, self.user, self.identity)
        self.login.assert_called_with(self.request, self.user)
        assert len(get_messages(self.request)) == 0

    def test_fxa_data_gets_set(self):
        assert len(get_messages(self.request)) == 0
        self.user.update(fxa_id=None)
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert not user.has_usable_password()
        assert len(get_messages(self.request)) == 1

    def test_email_address_can_change(self):
        assert len(get_messages(self.request)) == 0
        self.user.update(email='different@yeahoo.com')
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'
        assert len(get_messages(self.request)) == 0


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
        return APIRequestFactory().get(reverse('accounts.authenticate'))

    def login_error_url(self, **params):
        return urlparams(reverse('users.login'), **params)

    def render_error(self, error, next_path=None):
        return views.render_error(
            self.make_request(), error, format='html', next_path=next_path)

    def test_error_no_code_with_safe_path(self):
        response = self.render_error(
            views.ERROR_NO_CODE, next_path='/over/here')
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(to='/over/here', error=views.ERROR_NO_CODE))

    def test_error_no_profile_with_no_path(self):
        response = self.render_error(views.ERROR_NO_PROFILE)
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(error=views.ERROR_NO_PROFILE))

    def test_error_state_mismatch_with_unsafe_path(self):
        response = self.render_error(
            views.ERROR_STATE_MISMATCH,
            next_path='https://www.google.com/')
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(error=views.ERROR_STATE_MISMATCH))


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
        patcher = mock.patch('olympia.accounts.views.verify.fxa_identify')
        self.fxa_identify = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.accounts.views.find_user')
        self.find_user = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.accounts.views.render_error')
        self.render_error = patcher.start()
        self.addCleanup(patcher.stop)
        self.request = mock.MagicMock()
        self.user = UserProfile()
        self.request.user = self.user
        self.request.session = {'fxa_state': 'some-blob'}

    @views.with_user(format='json')
    def fn(*args, **kwargs):
        return args, kwargs

    def test_profile_exists_with_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.is_authenticated = lambda: False
        self.request.DATA = {'code': 'foo', 'state': 'some-blob'}
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
        self.user.is_authenticated = lambda: False
        # "/a/path/?" gets URL safe base64 encoded to L2EvcGF0aC8_.
        self.request.DATA = {
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
        self.user.is_authenticated = lambda: False
        # "/foo" gets URL safe base64 encoded to L2Zvbw== so it will be L2Zvbw.
        self.request.DATA = {
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
        self.user.is_authenticated = lambda: False
        self.request.DATA = {
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
        self.user.is_authenticated = lambda: False
        self.request.DATA = {
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
        self.user.is_authenticated = lambda: False
        self.request.DATA = {
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
        self.request.DATA = {'code': 'foo', 'state': 'some-blob'}
        self.user.is_authenticated = lambda: False
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': None,
            'identity': identity,
            'next_path': None,
        }

    def test_profile_does_not_exist(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        self.request.DATA = {'code': 'foo', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_NO_PROFILE, next_path=None,
            format='json')
        assert not self.find_user.called

    def test_code_not_provided(self):
        self.request.DATA = {'hey': 'hi', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_NO_CODE, next_path=None, format='json')
        assert not self.find_user.called
        assert not self.fxa_identify.called

    def test_logged_in_matches_identity(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.pk = 100
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_logged_in_does_not_match_identity_no_account(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = None
        self.user.pk = 100
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_logged_in_does_not_match_identity_fxa_id_blank(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = None
        self.user.pk = 100
        self.user.fxa_id = ''
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    def test_logged_in_does_not_match_identity_migrated(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = None
        self.user.pk = 100
        self.user.fxa_id = '4321'
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_USER_MIGRATED, next_path=None,
            format='json')

    def test_logged_in_does_not_match_conflict(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = mock.MagicMock(pk=222)
        self.user.pk = 100
        self.request.DATA = {
            'code': 'woah',
            'state': 'some-blob:{}'.format(
                base64.urlsafe_b64encode('https://www.google.com/')),
        }
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_USER_MISMATCH, next_path=None,
            format='json')

    def test_state_does_not_match(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.is_authenticated = lambda: False
        self.request.DATA = {
            'code': 'foo',
            'state': 'other-blob:{}'.format(base64.urlsafe_b64encode('/next')),
        }
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_STATE_MISMATCH, next_path='/next',
            format='json')


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
        assert not user.has_usable_password()
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
        assert not user.has_usable_password()


@override_settings(FXA_CONFIG=FXA_CONFIG)
class BaseAuthenticationView(APITestCase, InitializeSessionMixin):

    def setUp(self):
        self.url = reverse(self.view_name)
        create_switch('fxa-auth', active=True)
        self.fxa_identify = self.patch(
            'olympia.accounts.views.verify.fxa_identify')

    def patch(self, thing):
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()


class TestLoginView(BaseAuthenticationView):
    view_name = 'accounts.login'

    def setUp(self):
        super(TestLoginView, self).setUp()
        self.initialize_session({'fxa_state': 'some-blob'})
        self.login_user = self.patch('olympia.accounts.views.login_user')

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_CODE
        assert not self.login_user.called

    def test_wrong_state(self):
        response = self.client.post(
            self.url, {'code': 'foo', 'state': 'a-different-blob'})
        assert response.status_code == 400
        assert response.data['error'] == views.ERROR_STATE_MISMATCH
        assert not self.login_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 401
        assert response.data['error'] == views.ERROR_NO_PROFILE
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called

    def test_no_amo_account_cant_login(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com', 'uid': '5'}
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 422
        assert response.data['error'] == views.ERROR_NO_USER
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called

    def test_login_success(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'code', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        self.login_user.assert_called_with(mock.ANY, user, identity)

    def test_account_exists_migrated_multiple(self):
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
        assert not self.login_user.called


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
        self.register_user.return_value = UserProfile(email=identity['email'])
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
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

    def login_error_url(self, **params):
        return absolutify(urlparams(reverse('users.login'), **params))

    def test_no_code_provided(self):
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(error=views.ERROR_NO_CODE))
        assert not self.login_user.called
        assert not self.register_user.called

    def test_wrong_state(self):
        response = self.client.get(
            self.url, {'code': 'foo', 'state': '9f865be0'})
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(error=views.ERROR_STATE_MISMATCH))
        assert not self.login_user.called
        assert not self.register_user.called

    def test_no_fxa_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state})
        assert response.status_code == 302
        assert_url_equal(
            response['location'],
            self.login_error_url(error=views.ERROR_NO_PROFILE))
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        assert not self.register_user.called

    def test_success_no_account_registers(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': self.fxa_state})
        # This 302s because the user isn't logged in due to mocking.
        self.assertRedirects(
            response, reverse('users.edit'), target_status_code=302)
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)

    def test_register_redirects_edit(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
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

    def test_success_with_account_logs_in(self):
        user = UserProfile.objects.create(email='real@yeahoo.com', fxa_id='10')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'code', 'state': self.fxa_state})
        self.assertRedirects(response, reverse('home'))
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


class TestProfileView(APIAuthTestCase):

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


class TestAccountSourceView(APITestCase):

    def setUp(self):
        create_switch('fxa-auth', active=True)

    def get(self, email):
        return self.client.get(reverse('accounts.source'), {'email': email})

    def test_user_has_migrated(self):
        email = 'migrated@mozilla.org'
        UserProfile.objects.create(email=email, fxa_id='ya')
        response = self.get(email)
        assert response.status_code == 200
        assert response.data == {'source': 'fxa'}

    def test_user_has_not_migrated(self):
        email = 'not-migrated@mozilla.org'
        UserProfile.objects.create(email=email, fxa_id=None)
        response = self.get(email)
        assert response.status_code == 200
        assert response.data == {'source': 'amo'}

    def test_user_does_not_exist(self):
        response = self.get('no-user@mozilla.org')
        assert response.status_code == 200
        assert response.data == {'source': 'fxa'}
