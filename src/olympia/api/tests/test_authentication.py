import json

from calendar import timegm
from datetime import datetime, timedelta

from django.conf import settings
from django.core import signing
from django.test import RequestFactory

import jwt
import mock

from freezegun import freeze_time
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_jwt.views import refresh_jwt_token

from olympia import core
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    APITestClient, TestCase, WithDynamicEndpoints, user_factory)
from olympia.api.authentication import (
    JWTKeyAuthentication, WebTokenAuthentication)
from olympia.api.tests.test_jwt_auth import JWTAuthKeyTester


class JWTKeyAuthTestView(APIView):
    """
    This is an example of a view that would be protected by
    JWTKeyAuthentication, used in TestJWTKeyAuthProtectedView below.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTKeyAuthentication]

    def get(self, request):
        return Response('some get response')

    def post(self, request):
        return Response({'user_pk': request.user.pk})


class TestJWTKeyAuthentication(JWTAuthKeyTester):
    client_class = APITestClient

    def setUp(self):
        super(TestJWTKeyAuthentication, self).setUp()
        self.factory = RequestFactory()
        self.auth = JWTKeyAuthentication()
        self.user = user_factory(read_dev_agreement=datetime.now())

    def request(self, token):
        return self.factory.get('/', HTTP_AUTHORIZATION='JWT {}'.format(token))

    def _create_token(self, api_key=None):
        if api_key is None:
            api_key = self.create_api_key(self.user)
        return self.create_auth_token(api_key.user, api_key.key,
                                      api_key.secret)

    def test_get_user(self):
        core.set_remote_addr('15.16.23.42')
        user, _ = self.auth.authenticate(self.request(self._create_token()))
        assert user == self.user
        assert user.last_login_ip == '15.16.23.42'
        self.assertCloseToNow(user.last_login)

    def test_unknown_issuer(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['iss'] = 'non-existant-issuer'
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(token))
        assert ctx.exception.detail == 'Unknown JWT iss (issuer).'

    def test_deleted_user(self):
        in_the_past = self.days_ago(42)
        self.user.update(
            last_login_ip='48.15.16.23', last_login=in_the_past, deleted=True)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(self._create_token()))
        assert ctx.exception.detail == 'User account is disabled.'
        self.user.reload()
        assert self.user.last_login == in_the_past
        assert self.user.last_login_ip == '48.15.16.23'

    def test_user_has_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(self._create_token()))
        assert ctx.exception.detail == 'User has not read developer agreement.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_authentication_failed(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))

        assert ctx.exception.detail == 'Incorrect authentication credentials.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_expired_signature(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.ExpiredSignature

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))

        assert ctx.exception.detail == 'Signature has expired.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_decoding_error(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.DecodeError

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))
        assert ctx.exception.detail == 'Error decoding signature.'

    @mock.patch('olympia.api.jwt_auth.jwt_decode_handler')
    def test_decode_invalid_token(self, jwt_decode_handler):
        jwt_decode_handler.side_effect = jwt.InvalidTokenError

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request('whatever'))
        assert ctx.exception.detail == 'Invalid JWT Token.'

    def test_refuse_refreshable_tokens(self):
        # We should not accept refreshable tokens.
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['orig_iat'] = timegm(payload['iat'].utctimetuple())
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(token))
        assert ctx.exception.detail == (
            "API key based tokens are not refreshable, don't include "
            "`orig_iat` in their payload.")

    def test_cant_refresh_token(self):
        # Developers generate tokens, not us, they should not be refreshable,
        # the refresh implementation does not even know how to decode them.
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['orig_iat'] = timegm(payload['iat'].utctimetuple())
        token = self.encode_token_payload(payload, api_key.secret)

        request = self.factory.post('/lol-refresh', {'token': token})
        response = refresh_jwt_token(request)
        response.render()
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == {'non_field_errors': ['Error decoding signature.']}


class TestJWTKeyAuthProtectedView(WithDynamicEndpoints, JWTAuthKeyTester):
    client_class = APITestClient

    def setUp(self):
        super(TestJWTKeyAuthProtectedView, self).setUp()
        self.endpoint(JWTKeyAuthTestView)
        self.client.logout_api()  # just to be sure!
        self.user = user_factory(read_dev_agreement=datetime.now())

    def request(self, method, *args, **kw):
        handler = getattr(self.client, method)
        return handler('/en-US/firefox/dynamic-endpoint', *args, **kw)

    def jwt_request(self, token, method, *args, **kw):
        return self.request(method,
                            HTTP_AUTHORIZATION='JWT {}'.format(token),
                            *args, **kw)

    def test_get_requires_auth(self):
        res = self.request('get')
        assert res.status_code == 401, res.content

    def test_post_requires_auth(self):
        res = self.request('post', {})
        assert res.status_code == 401, res.content

    def test_can_post_with_jwt_header(self):
        api_key = self.create_api_key(self.user)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)
        res = self.jwt_request(token, 'post', {})

        assert res.status_code == 200, res.content
        data = json.loads(res.content)
        assert data['user_pk'] == self.user.pk

    def test_api_key_must_be_active(self):
        api_key = self.create_api_key(self.user, is_active=None)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)
        res = self.jwt_request(token, 'post', {})
        assert res.status_code == 401, res.content


class TestWebTokenAuthentication(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestWebTokenAuthentication, self).setUp()
        self.auth = WebTokenAuthentication()
        self.factory = RequestFactory()
        self.user = user_factory(read_dev_agreement=datetime.now())

    def _authenticate(self, token):
        url = absolutify('/api/v3/whatever/')
        prefix = WebTokenAuthentication.auth_header_prefix
        request = self.factory.post(
            url, HTTP_HOST='testserver',
            HTTP_AUTHORIZATION='{0} {1}'.format(prefix, token))

        return self.auth.authenticate(request)

    def test_success(self):
        token = self.client.generate_api_token(self.user)
        user, _ = self._authenticate(token)
        assert user == self.user

    def test_authenticate_header(self):
        request = self.factory.post('/api/v3/whatever/')
        assert (self.auth.authenticate_header(request) ==
                'bearer realm="api"')

    def test_wrong_header_only_prefix(self):
        request = self.factory.post(
            '/api/v3/whatever/',
            HTTP_AUTHORIZATION=WebTokenAuthentication.auth_header_prefix)
        with self.assertRaises(AuthenticationFailed) as exp:
            self.auth.authenticate(request)
        assert exp.exception.detail['code'] == 'ERROR_INVALID_HEADER'
        assert exp.exception.detail['detail'] == (
            'Invalid Authorization header. No credentials provided.')

    def test_wrong_header_too_many_spaces(self):
        request = self.factory.post(
            '/api/v3/whatever/',
            HTTP_AUTHORIZATION='{} foo bar'.format(
                WebTokenAuthentication.auth_header_prefix))
        with self.assertRaises(AuthenticationFailed) as exp:
            self.auth.authenticate(request)
        assert exp.exception.detail['code'] == 'ERROR_INVALID_HEADER'
        assert exp.exception.detail['detail'] == (
            'Invalid Authorization header. '
            'Credentials string should not contain spaces.')

    def test_no_token(self):
        request = self.factory.post('/api/v3/whatever/')
        self.auth.authenticate(request) is None

    def test_expired_token(self):
        old_date = datetime.now() - timedelta(
            seconds=settings.SESSION_COOKIE_AGE + 1)
        with freeze_time(old_date):
            token = self.client.generate_api_token(self.user)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_SIGNATURE_EXPIRED'
        assert exp.exception.detail['detail'] == 'Signature has expired.'

    def test_still_valid_token(self):
        not_so_old_date = datetime.now() - timedelta(
            seconds=settings.SESSION_COOKIE_AGE - 30)
        with freeze_time(not_so_old_date):
            token = self.client.generate_api_token(self.user)
        assert self._authenticate(token)[0] == self.user

    def test_bad_token(self):
        token = 'garbage'
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_DECODING_SIGNATURE'
        assert exp.exception.detail['detail'] == 'Error decoding signature.'

    def test_user_id_is_none(self):
        token = self.client.generate_api_token(self.user, user_id=None)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_no_user_id_in_payload(self):
        data = {
            'auth_hash': self.user.get_session_auth_hash(),
        }
        token = signing.dumps(data, salt=WebTokenAuthentication.salt)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_no_auth_hash_in_payload(self):
        data = {
            'user_id': self.user.pk,
        }
        token = signing.dumps(data, salt=WebTokenAuthentication.salt)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_user_deleted(self):
        self.user.delete()
        token = self.client.generate_api_token(self.user)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_invalid_user_not_found(self):
        token = self.client.generate_api_token(self.user, user_id=-1)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_invalid_user_other_user(self):
        user2 = user_factory(read_dev_agreement=datetime.now())
        token = self.client.generate_api_token(self.user, user_id=user2.pk)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_wrong_auth_id(self):
        token = self.client.generate_api_token(self.user)
        self.user.update(auth_id=self.user.auth_id + 42)
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(token)

    def test_make_sure_token_is_decodable(self):
        token = self.client.generate_api_token(self.user)
        # A token is really a string containing the json dict,
        # a timestamp and a signature, separated by ':'. The base64 encoding
        # lacks padding, which is why we need to use signing.b64_decode() which
        # handles that for us.
        data = json.loads(signing.b64_decode(token.split(':')[0]))
        assert data['user_id'] == self.user.pk
        assert data['auth_hash'] == self.user.get_session_auth_hash()
