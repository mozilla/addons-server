from unittest import TestCase

import mock
import pytest

from olympia.accounts import verify


class TestProfile(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.requests.get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_success(self):
        profile_data = {'email': 'yo@oy.com'}
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = profile_data
        profile = verify.get_fxa_profile(
            'profile-plz', {'profile_host': 'https://app.fxa/v1'}
        )
        assert profile == profile_data
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={'Authorization': 'Bearer profile-plz'},
        )

    def test_success_no_email(self):
        profile_data = {'email': ''}
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = profile_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_profile(
                'profile-plz', {'profile_host': 'https://app.fxa/v1'}
            )
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={'Authorization': 'Bearer profile-plz'},
        )

    def test_failure(self):
        profile_data = {'error': 'some error'}
        self.get.return_value.status_code = 400
        self.get.json.return_value = profile_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_profile(
                'profile-plz', {'profile_host': 'https://app.fxa/v1'}
            )
        self.get.assert_called_with(
            'https://app.fxa/v1/profile',
            headers={'Authorization': 'Bearer profile-plz'},
        )


class TestToken(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def test_success(self):
        token_data = {'access_token': 'c0de'}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        token = verify.get_fxa_token(
            'token-plz',
            {
                'client_id': 'test-client-id',
                'client_secret': "don't look",
                'oauth_host': 'https://app.fxa/oauth/v1',
            },
        )
        assert token == token_data
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
            },
        )

    def test_no_token(self):
        token_data = {'access_token': ''}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_token(
                'token-plz',
                {
                    'client_id': 'test-client-id',
                    'client_secret': "don't look",
                    'oauth_host': 'https://app.fxa/oauth/v1',
                },
            )
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
            },
        )

    def test_failure(self):
        token_data = {'error': 'some error'}
        self.post.return_value.status_code = 400
        self.post.json.return_value = token_data
        with pytest.raises(verify.IdentificationError):
            verify.get_fxa_token(
                'token-plz',
                {
                    'client_id': 'test-client-id',
                    'client_secret': "don't look",
                    'oauth_host': 'https://app.fxa/oauth/v1',
                },
            )
        self.post.assert_called_with(
            'https://app.fxa/oauth/v1/token',
            data={
                'code': 'token-plz',
                'client_id': 'test-client-id',
                'client_secret': "don't look",
            },
        )


class TestIdentify(TestCase):

    CONFIG = {'foo': 'bar'}

    def setUp(self):
        patcher = mock.patch('olympia.accounts.verify.get_fxa_token')
        self.get_token = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('olympia.accounts.verify.get_fxa_profile')
        self.get_profile = patcher.start()
        self.addCleanup(patcher.stop)

    def test_token_raises(self):
        self.get_token.side_effect = verify.IdentificationError
        with pytest.raises(verify.IdentificationError):
            verify.fxa_identify('heya', self.CONFIG)
        self.get_token.assert_called_with('heya', self.CONFIG)
        assert not self.get_profile.called

    def test_profile_raises(self):
        self.get_token.return_value = {'access_token': 'bee5'}
        self.get_profile.side_effect = verify.IdentificationError
        with pytest.raises(verify.IdentificationError):
            verify.fxa_identify('heya', self.CONFIG)
        self.get_token.assert_called_with('heya', self.CONFIG)
        self.get_profile.assert_called_with('bee5', self.CONFIG)

    def test_all_good(self):
        self.get_token.return_value = {'access_token': 'cafe'}
        self.get_profile.return_value = {'email': 'me@em.hi'}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {'email': 'me@em.hi'}
        self.get_token.assert_called_with('heya', self.CONFIG)
        self.get_profile.assert_called_with('cafe', self.CONFIG)
