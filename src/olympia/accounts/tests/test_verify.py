import time
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import pytest
from freezegun import freeze_time

from olympia.accounts import verify
from olympia.amo.tests import TestCase


class TestProfile(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.requests.get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(FXA_PROFILE_HOST='https://app.fxa/v1')
    def test_success(self):
        profile_data = {'email': 'yo@oy.com'}
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = profile_data
        profile = verify.get_fxa_profile('profile-plz', {})
        assert profile == profile_data
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={
                'Authorization': 'Bearer profile-plz',
            },
        )

    @override_settings(FXA_PROFILE_HOST='https://app.fxa/v1')
    def test_success_no_email(self):
        profile_data = {'email': ''}
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = profile_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_profile('profile-plz', {})
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={
                'Authorization': 'Bearer profile-plz',
            },
        )

    @override_settings(FXA_PROFILE_HOST='https://app.fxa/v1')
    def test_failure(self):
        profile_data = {'error': 'some error'}
        self.get.return_value.status_code = 400
        self.get.json.return_value = profile_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_profile('profile-plz', {})
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={
                'Authorization': 'Bearer profile-plz',
            },
        )


class TestToken(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    @override_settings(FXA_OAUTH_HOST='https://app.fxa/oauth/v1')
    def test_success(self):
        token_data = {'access_token': 'c0de'}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        token = verify.get_fxa_token(
            code='token-plz',
            config={
                'client_id': 'test-client-id',
                'client_secret': "don't look",
            },
        )
        assert token == token_data
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
                'grant_type': 'authorization_code',
            },
        )

    @override_settings(FXA_OAUTH_HOST='https://app.fxa/oauth/v1')
    def test_refresh_token_success(self):
        token_data = {'access_token': 'c0de'}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        token = verify.get_fxa_token(
            refresh_token='token-from-refresh-plz',
            config={
                'client_id': 'test-client-id',
                'client_secret': "don't look",
            },
        )
        assert token == token_data
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'refresh_token': 'token-from-refresh-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
                'grant_type': 'refresh_token',
            },
        )

    def test_neither_code_and_token_provided(self):
        with pytest.raises(AssertionError):
            verify.get_fxa_token(
                config={
                    'client_id': 'test-client-id',
                    'client_secret': "don't look",
                },
            )
        self.post.assert_not_called()

    @override_settings(FXA_OAUTH_HOST='https://app.fxa/oauth/v1')
    def test_no_token(self):
        token_data = {'access_token': ''}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_token(
                code='token-plz',
                config={
                    'client_id': 'test-client-id',
                    'client_secret': "don't look",
                },
            )
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
                'grant_type': 'authorization_code',
            },
        )

    @override_settings(FXA_OAUTH_HOST='https://app.fxa/oauth/v1')
    def test_failure(self):
        token_data = {'error': 'some error'}
        self.post.return_value.status_code = 400
        self.post.json.return_value = token_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_token(
                code='token-plz',
                config={
                    'client_id': 'test-client-id',
                    'client_secret': "don't look",
                },
            )
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
                'grant_type': 'authorization_code',
            },
        )


class TestIdentify(TestCase):

    CONFIG = {'foo': 'bar'}

    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.get_fxa_token')
        self.get_fxa_token = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.accounts.verify.get_fxa_profile')
        self.get_profile = patcher.start()
        self.addCleanup(patcher.stop)

    def test_token_raises(self):
        self.get_fxa_token.side_effect = verify.IdentificationError
        with pytest.raises(verify.IdentificationError):
            verify.fxa_identify('heya', self.CONFIG)
        self.get_fxa_token.assert_called_with(code='heya', config=self.CONFIG)
        assert not self.get_profile.called

    def test_profile_raises(self):
        self.get_fxa_token.return_value = {'access_token': 'bee5'}
        self.get_profile.side_effect = verify.IdentificationError
        with pytest.raises(verify.IdentificationError):
            verify.fxa_identify('heya', self.CONFIG)
        self.get_fxa_token.assert_called_with(code='heya', config=self.CONFIG)
        self.get_profile.assert_called_with('bee5', self.CONFIG)

    def test_all_good(self):
        self.get_fxa_token.return_value = get_fxa_token_data = {'access_token': 'cafe'}
        self.get_profile.return_value = {'email': 'me@em.hi'}
        identity, token_data = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {'email': 'me@em.hi'}
        assert token_data == get_fxa_token_data
        self.get_fxa_token.assert_called_with(code='heya', config=self.CONFIG)
        self.get_profile.assert_called_with('cafe', self.CONFIG)

    def test_with_id_token(self):
        self.get_fxa_token.return_value = get_fxa_token_data = {
            'access_token': 'cafe',
            'id_token': 'openidisawesome',
        }
        self.get_profile.return_value = {'email': 'me@em.hi'}
        identity, token_data = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {'email': 'me@em.hi'}
        assert token_data == get_fxa_token_data
        self.get_fxa_token.assert_called_with(code='heya', config=self.CONFIG)
        self.get_profile.assert_called_with('cafe', self.CONFIG)


@override_settings(USE_FAKE_FXA_AUTH=False, DEBUG=True)
class TestCheckAndUpdateFxaAccessToken(TestCase):
    def setUp(self):
        super().setUp()
        self.get_fxa_token_mock = self.patch('olympia.accounts.verify.get_fxa_token')

    def test_use_fake_fxa_auth(self):
        yesterday = datetime.now() - timedelta(days=1)
        request = mock.Mock()
        request.session = {'fxa_access_token_expiry': yesterday.timestamp()}
        with override_settings(USE_FAKE_FXA_AUTH=True):
            verify.check_and_update_fxa_access_token(request)
            self.get_fxa_token_mock.assert_not_called()

        verify.check_and_update_fxa_access_token(request)
        self.get_fxa_token_mock.assert_called()

    def test_verify_access_token_setting_false(self):
        yesterday = datetime.now() - timedelta(days=1)
        request = mock.Mock()
        request.session = {'fxa_access_token_expiry': yesterday.timestamp()}
        with override_settings(VERIFY_FXA_ACCESS_TOKEN=False):
            verify.check_and_update_fxa_access_token(request)
            self.get_fxa_token_mock.assert_not_called()

        verify.check_and_update_fxa_access_token(request)
        self.get_fxa_token_mock.assert_called()

    def test_session_access_token_expiry_okay(self):
        tomorrow = datetime.now() + timedelta(days=1)
        request = mock.Mock()
        request.session = {'fxa_access_token_expiry': tomorrow.timestamp()}

        verify.check_and_update_fxa_access_token(request)
        self.get_fxa_token_mock.assert_not_called()
        assert request.session['fxa_access_token_expiry'] == tomorrow.timestamp()

    @freeze_time()
    def test_refresh_success(self):
        yesterday = datetime.now() - timedelta(days=1)
        request = mock.Mock()
        request.session = {
            'fxa_access_token_expiry': yesterday.timestamp(),
            'fxa_refresh_token': 'refreshing!',
        }

        # successfull refresh:
        self.get_fxa_token_mock.return_value = {
            'id_token': 'someopenidtoken',
            'access_token': 'someaccesstoken',
            'expires_in': 123,
            'access_token_expiry': time.time() + 123,
        }

        verify.check_and_update_fxa_access_token(request)
        self.get_fxa_token_mock.assert_called_with(
            refresh_token='refreshing!', config=settings.FXA_CONFIG['default']
        )
        assert request.session['fxa_access_token_expiry'] == (
            self.get_fxa_token_mock.return_value['access_token_expiry']
        )

    @freeze_time()
    def test_refresh_fail(self):
        yesterday = datetime.now() - timedelta(days=1)
        request = mock.Mock()
        request.session = {
            'fxa_access_token_expiry': yesterday.timestamp(),
            'fxa_refresh_token': 'refreshing!',
        }

        self.get_fxa_token_mock.side_effect = verify.IdentificationError()
        with self.assertRaises(verify.IdentificationError):
            verify.check_and_update_fxa_access_token(request)
        self.get_fxa_token_mock.assert_called_with(
            refresh_token='refreshing!', config=settings.FXA_CONFIG['default']
        )
        # i.e. it's still expired
        assert request.session['fxa_access_token_expiry'] == yesterday.timestamp()
