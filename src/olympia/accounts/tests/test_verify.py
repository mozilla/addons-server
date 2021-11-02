from datetime import datetime, timedelta
from unittest import mock, TestCase

from django.conf import settings
from django.test.utils import override_settings

import pytest
from freezegun import freeze_time

from olympia.accounts import verify
from olympia.amo.tests import user_factory
from olympia.users.models import FxaToken


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


class TestFxaAccessTokenIsValid(TestCase):
    @mock.patch('olympia.accounts.verify.get_fxa_token')
    def test_no_valid_token(self, get_fxa_token_mock):
        expiry = datetime.now() + timedelta(days=1)
        user_token = FxaToken.objects.create(
            user=user_factory(),
            refresh_token='b',
            access_token_expiry=expiry,
            config_name='foo',
        )
        # different user
        assert not verify.update_fxa_access_token(
            {
                'user_token_pk': user_token.pk,
                'access_token_expiry': expiry,
            },
            user_factory(),
        )
        get_fxa_token_mock.assert_not_called()

        # works otherwise
        assert verify.update_fxa_access_token(
            {
                'user_token_pk': user_token.pk,
                'access_token_expiry': expiry,
            },
            user_token.user,
        )
        get_fxa_token_mock.assert_not_called()

        # but only with that pk
        assert not verify.update_fxa_access_token(
            {
                'user_token_pk': user_token.pk + 1,
                'access_token_expiry': expiry,
            },
            user_token.user,
        )
        get_fxa_token_mock.assert_not_called()

    @freeze_time()
    @mock.patch('olympia.accounts.verify.get_fxa_token')
    def test_refreshing(self, get_fxa_token_mock):
        expiry = datetime.now() - timedelta(days=1)
        user_token = FxaToken.objects.create(
            user=user_factory(),
            refresh_token='b',
            access_token_expiry=expiry,
            config_name='foo',
        )

        # successfull refresh:
        get_fxa_token_mock.return_value = {
            'id_token': 'someopenidtoken',
            'access_token': 'someaccesstoken',
            'refresh_token': 'somerefreshtoken',
            'expires_in': 123,
        }
        session_dict = {
            'user_token_pk': user_token.pk,
            'access_token_expiry': expiry,
        }
        assert verify.update_fxa_access_token(session_dict, user_token.user)
        get_fxa_token_mock.assert_called_with(
            refresh_token='b', config=settings.FXA_CONFIG['default']
        )
        user_token.reload()
        assert user_token.access_token == 'someaccesstoken'
        assert user_token.access_token_expiry == datetime.now() + timedelta(seconds=123)
        assert user_token.refresh_token == 'somerefreshtoken'
        assert session_dict['access_token_expiry'] == user_token.access_token_expiry

        # and now it's valid
        get_fxa_token_mock.reset_mock()
        assert verify.update_fxa_access_token(session_dict, user_token.user)
        get_fxa_token_mock.assert_not_called()

        # failed refresh
        user_token.update(access_token_expiry=datetime.now() - timedelta(days=1))
        session_dict['access_token_expiry'] = user_token.access_token_expiry
        get_fxa_token_mock.side_effect = verify.IdentificationError()
        assert not verify.update_fxa_access_token(session_dict, user_token.user)
        get_fxa_token_mock.assert_called_with(
            refresh_token='somerefreshtoken', config=settings.FXA_CONFIG['default']
        )
        # i.e. it's still expired
        assert session_dict['access_token_expiry'] == user_token.access_token_expiry
