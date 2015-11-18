from unittest import TestCase

import mock

from apps.accounts import verify


class TestProfile(TestCase):

    def setUp(self):
        patcher = mock.patch('apps.accounts.verify.requests.get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_profile_success(self):
        profile_data = {'email': 'yo@oy.com'}
        self.get.return_value.status_code = 200
        self.get.return_value.json.return_value = profile_data
        profile = verify.get_fxa_profile('profile-plz', {
            'profile_uri': 'https://fxa.com/v1',
        })
        assert profile == profile_data
        self.get.assert_called_with('https://fxa.com/v1/profile', headers={
            'Authorization': 'Bearer profile-plz',
        })

    def test_get_profile_failure(self):
        profile_data = {'error': 'some error'}
        self.get.return_value.status_code = 400
        self.get.json.return_value = profile_data
        profile = verify.get_fxa_profile('profile-plz', {
            'profile_uri': 'https://fxa.com/v1',
        })
        assert profile == {}
        self.get.assert_called_with('https://fxa.com/v1/profile', headers={
            'Authorization': 'Bearer profile-plz',
        })


class TestToken(TestCase):

    def setUp(self):
        patcher = mock.patch('apps.accounts.verify.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_token_success(self):
        token_data = {'email': 'yo@oy.com'}
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = token_data
        token = verify.get_fxa_token('token-plz', {
            'client_id': 'test-client-id',
            'client_secret': "don't look",
            'oauth_uri': 'https://fxa.com/oauth/v1',
        })
        assert token == token_data
        self.post.assert_called_with('https://fxa.com/oauth/v1/token', data={
            'code': 'token-plz',
            'client_id': 'test-client-id',
            'client_secret': "don't look",
        })

    def test_get_token_failure(self):
        token_data = {'error': 'some error'}
        self.post.return_value.status_code = 400
        self.post.json.return_value = token_data
        token = verify.get_fxa_token('token-plz', {
            'client_id': 'test-client-id',
            'client_secret': "don't look",
            'oauth_uri': 'https://fxa.com/oauth/v1',
        })
        assert token == {}
        self.post.assert_called_with('https://fxa.com/oauth/v1/token', data={
            'code': 'token-plz',
            'client_id': 'test-client-id',
            'client_secret': "don't look",
        })


class TestIdentify(TestCase):

    CONFIG = {'foo': 'bar'}

    def setUp(self):
        patcher = mock.patch('apps.accounts.verify.get_fxa_token')
        self.get_token = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('apps.accounts.verify.get_fxa_profile')
        self.get_profile = patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_token(self):
        self.get_token.return_value = {}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {}
        self.get_token.assert_called_with('heya', self.CONFIG)
        assert not self.get_profile.called

    def test_no_profile(self):
        self.get_token.return_value = {'access_token': 'totes'}
        self.get_profile.return_value = {}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {}
        self.get_token.assert_called_with('heya', self.CONFIG)
        self.get_profile.assert_called_with('totes', self.CONFIG)

    def test_all_good(self):
        self.get_token.return_value = {'access_token': 'totes'}
        self.get_profile.return_value = {'email': 'me@em.hi'}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {'email': 'me@em.hi'}
        self.get_token.assert_called_with('heya', self.CONFIG)
        self.get_profile.assert_called_with('totes', self.CONFIG)
