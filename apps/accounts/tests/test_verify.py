# No django imports.

import mock

from apps.accounts import verify


class TestProfile(object):

    @mock.patch('apps.accounts.verify.requests.get')
    def test_get_profile_success(self, get):
        profile_data = {'email': 'yo@oy.com'}
        get.return_value.status_code = 200
        get.return_value.json.return_value = profile_data
        profile = verify.get_fxa_profile('profile-plz', {
            'profile_uri': 'https://fxa.com/v1',
        })
        assert profile == profile_data
        get.assert_called_with('https://fxa.com/v1/profile', headers={
            'Authorization': 'Bearer profile-plz',
        })

    @mock.patch('apps.accounts.verify.requests.get')
    def test_get_profile_failure(self, get):
        profile_data = {'error': 'some error'}
        get.return_value.status_code = 400
        get.json.return_value = profile_data
        profile = verify.get_fxa_profile('profile-plz', {
            'profile_uri': 'https://fxa.com/v1',
        })
        assert profile == {}
        get.assert_called_with('https://fxa.com/v1/profile', headers={
            'Authorization': 'Bearer profile-plz',
        })


class TestToken(object):

    @mock.patch('apps.accounts.verify.requests.post')
    def test_get_token_success(self, post):
        token_data = {'email': 'yo@oy.com'}
        post.return_value.status_code = 200
        post.return_value.json.return_value = token_data
        token = verify.get_fxa_token('token-plz', {
            'client_id': 'test-client-id',
            'client_secret': "don't look",
            'oauth_uri': 'https://fxa.com/oauth/v1',
        })
        assert token == token_data
        post.assert_called_with('https://fxa.com/oauth/v1/token', data={
            'code': 'token-plz',
            'client_id': 'test-client-id',
            'client_secret': "don't look",
        })

    @mock.patch('apps.accounts.verify.requests.post')
    def test_get_token_failure(self, post):
        token_data = {'error': 'some error'}
        post.return_value.status_code = 400
        post.json.return_value = token_data
        token = verify.get_fxa_token('token-plz', {
            'client_id': 'test-client-id',
            'client_secret': "don't look",
            'oauth_uri': 'https://fxa.com/oauth/v1',
        })
        assert token == {}
        post.assert_called_with('https://fxa.com/oauth/v1/token', data={
            'code': 'token-plz',
            'client_id': 'test-client-id',
            'client_secret': "don't look",
        })


class TestIdentify(object):

    CONFIG = {'foo': 'bar'}

    @mock.patch('apps.accounts.verify.get_fxa_token')
    @mock.patch('apps.accounts.verify.get_fxa_profile')
    def test_no_token(self, get_profile, get_token):
        get_token.return_value = {}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {}
        get_token.assert_called_with('heya', self.CONFIG)
        assert not get_profile.called

    @mock.patch('apps.accounts.verify.get_fxa_token')
    @mock.patch('apps.accounts.verify.get_fxa_profile')
    def test_no_profile(self, get_profile, get_token):
        get_token.return_value = {'access_token': 'totes'}
        get_profile.return_value = {}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {}
        get_token.assert_called_with('heya', self.CONFIG)
        get_profile.assert_called_with('totes', self.CONFIG)

    @mock.patch('apps.accounts.verify.get_fxa_token')
    @mock.patch('apps.accounts.verify.get_fxa_profile')
    def test_all_good(self, get_profile, get_token):
        get_token.return_value = {'access_token': 'totes'}
        get_profile.return_value = {'email': 'me@em.hi'}
        identity = verify.fxa_identify('heya', self.CONFIG)
        assert identity == {'email': 'me@em.hi'}
        get_token.assert_called_with('heya', self.CONFIG)
        get_profile.assert_called_with('totes', self.CONFIG)
