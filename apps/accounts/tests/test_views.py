from django.core.urlresolvers import reverse
from django.test.utils import override_settings

import mock

from rest_framework.test import APITestCase
from waffle import Switch

from users.models import UserProfile

FXA_CONFIG = {'some': 'stuff', 'that is': 'needed'}


class override_switch(object):
    def __init__(self, name, active):
        self.name = name
        self.active = active

    def __enter__(self):
        Switch.objects.create(name=self.name, active=self.active)

    def __exit__(self, exc_type, exc_val, exc_tb):
        Switch.objects.filter(name=self.name).delete()


class TestFxALoginWaffle(APITestCase):

    @property
    def url(self):
        return reverse('accounts.login')

    def test_404_when_waffle_is_off(self):
        with override_switch('fxa-auth', active=False):
            response = self.client.post(self.url)
            assert response.status_code == 404

    def test_400_when_waffle_is_on(self):
        with override_switch('fxa-auth', active=True):
            response = self.client.post(self.url)
            assert response.status_code == 400


@override_settings(FXA_CONFIG=FXA_CONFIG)
class TestLoginView(APITestCase):

    def setUp(self):
        Switch.objects.create(name='fxa-auth', active=True)
        patcher = mock.patch('accounts.views.verify.fxa_identify')
        self.fxa_identify = patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def url(self):
        return reverse('accounts.login')

    def test_no_code_provided(self):
        response = self.client.post(self.url)
        assert response.status_code == 400
        assert response.data['error'] == 'No code provided.'

    def test_no_email_returned(self):
        self.fxa_identify.return_value = {}
        response = self.client.post(self.url, {'code': 'foo'})
        assert response.status_code == 401
        assert response.data['error'] == 'Could not log you in.'
        self.fxa_identify.assert_called_with('foo', config=FXA_CONFIG)

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
