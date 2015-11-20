from django.core.urlresolvers import resolve, reverse
from django.test.utils import override_settings

import mock

from rest_framework.test import APITestCase

from accounts import verify
from amo.tests import create_switch
from api.tests.utils import APIAuthTestCase
from users.models import UserProfile

FXA_CONFIG = {'some': 'stuff', 'that is': 'needed'}


class TestFxALoginWaffle(APITestCase):

    def setUp(self):
        self.login_url = reverse('accounts.login')
        self.register_url = reverse('accounts.register')

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


@override_settings(FXA_CONFIG=FXA_CONFIG)
class TestLoginView(APITestCase):

    def setUp(self):
        self.url = reverse('accounts.login')
        create_switch('fxa-auth', active=True)
        patcher = mock.patch('accounts.views.verify.fxa_identify')
        self.fxa_identify = patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 422
        assert response.data['error'] == 'No code provided.'

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_no_account(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com', 'uid': '5'}
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 422
        assert response.data['error'] == 'User does not exist.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_logs_user_in(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        assert '_auth_user_id' not in self.client.session
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9001'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 200
        assert '_auth_user_id' in self.client.session
        assert self.client.session['_auth_user_id'] == user.pk

    def test_identify_success_sets_fxa_data(self):
        user = UserProfile.objects.create(email='real@yeahoo.com')
        assert user.fxa_id is None
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9001'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 200
        user = user.reload()
        assert user.fxa_id == '9001'
        assert not user.has_usable_password()

    def test_identify_success_account_exists_migrated_different_email(self):
        user = UserProfile.objects.create(email='different@yeahoo.com',
                                          fxa_id='9005')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9005'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 200
        self.fxa_identify.assert_called_with('code', config=FXA_CONFIG)
        user = user.reload()
        assert user.fxa_id == '9005'
        assert user.email == 'real@yeahoo.com'

    def test_identify_success_account_exists_not_migrated(self):
        UserProfile.objects.create(email='real@yeahoo.com')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9001'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
        self.fxa_identify.assert_called_with('code', config=FXA_CONFIG)

    def test_identify_success_account_exists_migrated_multiple(self):
        UserProfile.objects.create(email='real@yeahoo.com', username='foo')
        UserProfile.objects.create(
            email='different@yeahoo.com', fxa_id='9005', username='bar')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '9005'}
        with self.assertRaises(UserProfile.MultipleObjectsReturned):
            self.client.post(self.url, {'code': 'code'})


@override_settings(FXA_CONFIG=FXA_CONFIG)
class TestRegisterView(APITestCase):

    def setUp(self):
        self.url = reverse('accounts.register')
        create_switch('fxa-auth', active=True)
        patcher = mock.patch('accounts.views.verify.fxa_identify')
        self.fxa_identify = patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 422
        assert response.data['error'] == 'No code provided.'

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_no_account(self):
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        self.fxa_identify.return_value = {u'email': u'me@yeahoo.com',
                                          u'uid': u'e0b6f'}

        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
        assert user_qs.exists()
        user = user_qs.get()
        assert user.username == 'me@yeahoo.com'
        assert user.fxa_id == 'e0b6f'
        assert not user.has_usable_password()
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_logs_user_in(self):
        assert '_auth_user_id' not in self.client.session
        self.fxa_identify.return_value = {u'email': u'me@yeahoo.com',
                                          u'uid': u'e0b6f'}
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 200
        user = UserProfile.objects.get(email='me@yeahoo.com')
        assert '_auth_user_id' in self.client.session
        assert self.client.session['_auth_user_id'] == user.pk

    def test_identify_success_no_account_username_taken(self):
        UserProfile.objects.create(
            email='you@yeahoo.com', username='me@yeahoo.com')
        user_qs = UserProfile.objects.filter(email='me@yeahoo.com')
        assert not user_qs.exists()
        self.fxa_identify.return_value = {u'email': u'me@yeahoo.com',
                                          u'uid': u'e0b6f'}

        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 200
        assert response.data['email'] == 'me@yeahoo.com'
        assert user_qs.exists()
        user = user_qs.get()
        assert user.username.startswith('me@yeahoo.com')
        assert user.username != 'me@yeahoo.com'
        assert user.fxa_id == 'e0b6f'
        assert not user.has_usable_password()
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_account_exists_email(self):
        UserProfile.objects.create(email='real@yeahoo.com')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com',
                                          'uid': '8675'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 422
        assert response.data['error'] == 'That account already exists.'
        self.fxa_identify.assert_called_with('code', config=FXA_CONFIG)

    def test_identify_success_account_exists_uid(self):
        UserProfile.objects.create(email='real@yeahoo.com', fxa_id='10')
        self.fxa_identify.return_value = {'email': 'diff@yeahoo.com',
                                          'uid': '10'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 422
        assert response.data['error'] == 'That account already exists.'
        self.fxa_identify.assert_called_with('code', config=FXA_CONFIG)


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
