import base64

from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.core.urlresolvers import resolve, reverse
from django.test.utils import override_settings
import mock
from waffle.models import Switch

from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework_jwt.serializers import VerifyJSONWebTokenSerializer

from olympia.access.acl import action_allowed_user
from olympia.access.models import Group, GroupUser
from olympia.accounts import verify, views
from olympia.amo.helpers import absolutify, urlparams
from olympia.amo.tests import (
    assert_url_equal, create_switch, InitializeSessionMixin, TestCase)
from olympia.api.tests.utils import APIKeyAuthTestCase
from olympia.users.models import UserProfile

FXA_CONFIG = {'some': 'stuff', 'that is': 'needed'}


class TestFxALoginWaffle(APITestCase):

    def setUp(self):
        self.login_url = reverse('accounts.login')
        self.register_url = reverse('accounts.register')
        self.source_url = reverse('accounts.source')

    def test_login_422_when_waffle_is_on(self):
        response = self.client.post(self.login_url)
        assert response.status_code == 422

    def test_register_422_when_waffle_is_on(self):
        response = self.client.post(self.register_url)
        assert response.status_code == 422

    def test_source_200_when_waffle_is_on(self):
        response = self.client.get(self.source_url, {'email': 'u@example.com'})
        assert response.status_code == 200


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
        request = APIRequestFactory().get(reverse('accounts.authenticate'))
        request.user = AnonymousUser()
        return self.enable_messages(request)

    def login_url(self, **params):
        return urlparams(reverse('users.login'), **params)

    def migrate_url(self, **params):
        return absolutify(urlparams(reverse('users.migrate'), **params))

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
        assert_url_equal(response['location'], self.login_url(to='/over/here'))

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

    def test_error_no_code_with_safe_path_logged_in(self):
        request = self.make_request()
        request.user = UserProfile()
        assert len(get_messages(request)) == 0
        response = self.render_error(
            request, views.ERROR_NO_CODE, next_path='/over/here')
        assert response.status_code == 302
        messages = get_messages(request)
        assert len(messages) == 1
        assert 'could not be parsed' in next(iter(messages)).message
        assert_url_equal(
            response['location'],
            self.migrate_url(to='/over/here'))


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
        self.request.data = {'code': 'foo', 'state': 'some-blob'}
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': self.user,
            'identity': identity,
            'next_path': None,
        }

    @override_settings(FXA_CONFIG={'default': {}})
    def test_unknown_config_blows_up_early(self):
        with self.assertRaises(AssertionError):
            views.with_user(format='json', config='notconfigured')

    def test_profile_exists_with_user_and_path(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.is_authenticated = lambda: False
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
        self.user.is_authenticated = lambda: False
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
        self.user.is_authenticated = lambda: False
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
        self.user.is_authenticated = lambda: False
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
        self.user.is_authenticated = lambda: False
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

    def test_logged_in_matches_identity(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.pk = 100
        self.request.data = {'code': 'woah', 'state': 'some-blob'}
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
        self.request.data = {'code': 'woah', 'state': 'some-blob'}
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
        self.request.data = {'code': 'woah', 'state': 'some-blob'}
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
        self.request.data = {'code': 'woah', 'state': 'some-blob'}
        self.fn(self.request)
        self.render_error.assert_called_with(
            self.request, views.ERROR_USER_MIGRATED, next_path=None,
            format='json')

    def test_logged_in_does_not_match_conflict(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = mock.MagicMock(pk=222)
        self.user.pk = 100
        self.request.data = {
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
        self.request.data = {
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


@override_settings(FXA_CONFIG={'default': FXA_CONFIG})
class BaseAuthenticationView(APITestCase, InitializeSessionMixin):

    def setUp(self):
        self.url = reverse(self.view_name)
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
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'code', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        assert (response.cookies['jwt_api_auth_token'].value ==
                response.data['token'])
        verify = VerifyJSONWebTokenSerializer().validate(response.data)
        assert verify['user'] == user
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
        user = UserProfile(username='foobar', email=identity['email'])
        self.register_user.return_value = user
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
        assert (response.cookies['jwt_api_auth_token'].value ==
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
        user = UserProfile.objects.create(
            username='foobar', email='real@yeahoo.com', fxa_id='10')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'code', 'state': self.fxa_state})
        self.assertRedirects(response, reverse('home'))
        data = {'token': response.cookies['jwt_api_auth_token'].value}
        verify = VerifyJSONWebTokenSerializer().validate(data)
        assert verify['user'] == user
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


class TestAccountSourceView(APITestCase):

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

    def test_multiple_users_returned(self):
        UserProfile.objects.create(username='alice', email=None)
        UserProfile.objects.create(username='bob', email=None)
        response = self.client.get(reverse('accounts.source'))
        assert response.status_code == 422
        assert response.data == {'error': 'Email is required.'}


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

    def test_create_a_user_with_custom_password(self):
        password = 'I once ate a three day old nacho'
        res = self.post(self.url, {'password': password})
        assert res.status_code == 201, res.content
        user = UserProfile.objects.get(pk=res.data['user_id'])
        assert user.check_password(password)

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
