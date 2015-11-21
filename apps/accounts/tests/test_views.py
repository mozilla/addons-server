import json

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
        self.url = reverse('accounts.login')

    def test_404_when_waffle_is_off(self):
        create_switch('fxa-auth', active=False)
        response = self.client.post(self.url)
        assert response.status_code == 404

    def test_400_when_waffle_is_on(self):
        create_switch('fxa-auth', active=True)
        response = self.client.post(self.url)
        assert response.status_code == 400


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
        assert response.status_code == 400
        assert response.data['error'] == 'No code provided.'

    def test_identify_no_profile(self):
        self.fxa_identify.side_effect = verify.IdentificationError
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 401
        assert response.data['error'] == 'Profile not found.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_no_account(self):
        self.fxa_identify.return_value = {'email': 'me@yeahoo.com'}
        response = self.client.post(self.url, {'code': 'codes!!'})
        assert response.status_code == 400
        assert response.data['error'] == 'User does not exist.'
        self.fxa_identify.assert_called_with('codes!!', config=FXA_CONFIG)

    def test_identify_success_account_exists(self):
        UserProfile.objects.create(email='real@yeahoo.com')
        self.fxa_identify.return_value = {'email': 'real@yeahoo.com'}
        response = self.client.post(self.url, {'code': 'code'})
        assert response.status_code == 200
        assert response.data['email'] == 'real@yeahoo.com'
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
        assert json.loads(res.content)['email'] == 'a@m.o'

    def test_auth_required(self):
        self.auth_required(self.cls)

    def test_verbs_allowed(self):
        self.verbs_allowed(self.cls, ['get'])
