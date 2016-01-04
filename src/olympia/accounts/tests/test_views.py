import base64

from django.core.urlresolvers import resolve, reverse
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings

import mock

from rest_framework.test import APITestCase

from olympia.accounts import verify, views
from olympia.amo.tests import create_switch, InitializeSessionMixin
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
        self.request = RequestFactory().get('/login')
        self.user = UserProfile.objects.create(email='real@yeahoo.com')
        self.identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        patcher = mock.patch('olympia.accounts.views.login')
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def test_user_gets_logged_in(self):
        views.login_user(self.request, self.user, self.identity)
        self.login.assert_called_with(self.request, self.user)

    def test_identify_success_sets_fxa_data(self):
        assert self.user.fxa_id is None
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert not user.has_usable_password()

    def test_identify_success_account_exists_migrated_different_email(self):
        self.user.update(email='different@yeahoo.com')
        views.login_user(self.request, self.user, self.identity)
        user = self.user.reload()
        assert user.fxa_id == '9001'
        assert user.email == 'real@yeahoo.com'


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


class TestWithUser(TestCase):

    def setUp(self):
        patcher = mock.patch('olympia.accounts.views.verify.fxa_identify')
        self.fxa_identify = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.accounts.views.find_user')
        self.find_user = patcher.start()
        self.addCleanup(patcher.stop)
        self.request = mock.MagicMock()
        self.user = mock.MagicMock(fxa_id=None)
        self.user.is_authenticated.return_value = True
        self.request.user = self.user
        self.request.session = {'fxa_state': 'some-blob'}

    @views.with_user
    def fn(*args, **kwargs):
        return args, kwargs

    def test_profile_exists_with_user(self):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.is_authenticated.return_value = False
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
        self.user.is_authenticated.return_value = False
        # "/a/path/?" gets URL safe base64 encoded to L2EvcGF0aC8_.
        self.request.DATA = {
            'code': 'foo',
            'state': u'some-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode("/a/path/?")),
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
        self.user.is_authenticated.return_value = False
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
        self.user.is_authenticated.return_value = False
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
        self.user.is_authenticated.return_value = False
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
        self.user.is_authenticated.return_value = False
        self.request.DATA = {
            'code': 'foo',
            'state': u'some-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode("https://www.google.com")),
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
        self.user.is_authenticated.return_value = False
        args, kwargs = self.fn(self.request)
        assert args == (self, self.request)
        assert kwargs == {
            'user': None,
            'identity': identity,
            'next_path': None,
        }

    @mock.patch('olympia.accounts.views.Response')
    def test_profile_does_not_exist(self, Response):
        self.fxa_identify.side_effect = verify.IdentificationError
        self.request.DATA = {'code': 'foo', 'state': 'some-blob'}
        self.fn(self.request)
        Response.assert_called_with(
            {'error': 'Profile not found.'}, status=401)
        assert not self.find_user.called

    @mock.patch('olympia.accounts.views.Response')
    def test_code_not_provided(self, Response):
        self.request.DATA = {'hey': 'hi', 'state': 'some-blob'}
        self.fn(self.request)
        Response.assert_called_with(
            {'error': 'No code provided.'}, status=422)
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

    @mock.patch('olympia.accounts.views.Response')
    def test_logged_in_does_not_match_identity_migrated(self, Response):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = None
        self.user.pk = 100
        self.user.fxa_id = '4321'
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        self.fn(self.request)
        Response.assert_called_with(
            {'error': 'User already migrated.'}, status=422)

    @mock.patch('olympia.accounts.views.Response')
    def test_logged_in_does_not_match_conflict(self, Response):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = mock.MagicMock(pk=222)
        self.user.pk = 100
        self.request.DATA = {'code': 'woah', 'state': 'some-blob'}
        self.fn(self.request)
        Response.assert_called_with({'error': 'User mismatch.'}, status=422)

    @mock.patch('olympia.accounts.views.Response')
    def test_state_does_not_match(self, Response):
        identity = {'uid': '1234', 'email': 'hey@yo.it'}
        self.fxa_identify.return_value = identity
        self.find_user.return_value = self.user
        self.user.is_authenticated.return_value = False
        self.request.DATA = {'code': 'foo', 'state': 'other-blob'}
        self.fn(self.request)
        Response.assert_called_with({'error': 'State mismatch.'}, status=400)


class TestRegisterUser(TestCase):

    def setUp(self):
        self.request = RequestFactory().get('/register')
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
        assert user.username == 'me@yeahoo.com'
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
        assert user.username.startswith('me@yeahoo.com')
        assert user.username != 'me@yeahoo.com'
        assert user.fxa_id == '9005'
        assert not user.has_usable_password()


@override_settings(FXA_CONFIG=FXA_CONFIG)
class BaseAuthenticationView(APITestCase, InitializeSessionMixin):

    def setUp(self):
        self.url = reverse(self.view_name)
        create_switch('fxa-auth', active=True)
        self.fxa_identify = self.patch('olympia.accounts.views.verify.fxa_identify')

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
        assert response.data['error'] == 'No code provided.'
        assert not self.login_user.called

    def test_wrong_state(self):
        response = self.client.post(
            self.url, {'code': 'foo', 'state': 'a-different-blob'})
        assert response.status_code == 400
        assert response.data['error'] == 'State mismatch.'
        assert not self.login_user.called

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called

    def test_identify_success_no_account(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com', 'uid': '5'}
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 422
        assert response.data['error'] == 'User does not exist.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called

    def test_identify_success_account_exists(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'code', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        self.login_user.assert_called_with(mock.ANY, user, identity)

    def test_identify_success_account_exists_migrated_multiple(self):
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
        assert response.data['error'] == 'No code provided.'
        assert not self.register_user.called

    def test_wrong_state(self):
        response = self.client.post(
            self.url, {'code': 'foo', 'state': 'wrong-blob'})
        assert response.status_code == 400
        assert response.data['error'] == 'State mismatch.'
        assert not self.register_user.called

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.register_user.called

    def test_identify_success_no_account(self):
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.register_user.return_value = UserProfile(email=identity['email'])
        self.fxa_identify.return_value = identity
        response = self.client.post(
            self.url, {'code': 'codes!!', 'state': 'some-blob'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        self.register_user.assert_called_with(mock.ANY, identity)


class TestAuthorizeView(BaseAuthenticationView):
    view_name = 'accounts.authorize'

    def setUp(self):
        super(TestAuthorizeView, self).setUp()
        self.initialize_session({'fxa_state': 'the-right-blob'})
        self.login_user = self.patch('olympia.accounts.views.login_user')
        self.register_user = self.patch('olympia.accounts.views.register_user')

    def test_no_code_provided(self):
        response = self.client.get(self.url)
        assert response.status_code == 422
        assert response.data['error'] == 'No code provided.'
        assert not self.login_user.called
        assert not self.register_user.called

    def test_wrong_state(self):
        response = self.client.get(
            self.url, {'code': 'foo', 'state': 'the-wrong-blob'})
        assert response.status_code == 400
        assert response.data['error'] == 'State mismatch.'
        assert not self.login_user.called
        assert not self.register_user.called

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': 'the-right-blob'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        assert not self.register_user.called

    def test_identify_success_no_account(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'codes!!', 'state': 'the-right-blob'})
        assert response.status_code == 302
        assert response['location'] == 'http://testserver/'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)

    def test_identify_success_no_account_with_path(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        identity = {u'email': u'me@yeahoo.com', u'uid': u'e0b6f'}
        self.fxa_identify.return_value = identity
        response = self.client.get(self.url, {
            'code': 'codes!!',
            'state': 'the-right-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode('/go/here')),
        })
        assert response.status_code == 302
        assert response['location'] == 'http://testserver/go/here'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)
        assert not self.login_user.called
        self.register_user.assert_called_with(mock.ANY, identity)

    def test_identify_success_exists_logs_user_in(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(
            self.url, {'code': 'code', 'state': 'the-right-blob'})
        assert response.status_code == 302
        assert response['location'] == 'http://testserver/'
        self.login_user.assert_called_with(mock.ANY, user, identity)
        assert not self.register_user.called

    def test_identify_success_exists_logs_user_in_with_path(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        identity = {'email': 'real@yeahoo.com', 'uid': '9001'}
        self.fxa_identify.return_value = identity
        response = self.client.get(self.url, {
            'code': 'code',
            'state': 'the-right-blob:{next_path}'.format(
                next_path=base64.urlsafe_b64encode('/some/path')),
        })
        assert response.status_code == 302
        assert response['location'] == 'http://testserver/some/path'
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
