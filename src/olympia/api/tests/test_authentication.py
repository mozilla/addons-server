import json
import time

from calendar import timegm
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.test import RequestFactory
from django.urls import reverse

import jwt

from freezegun import freeze_time
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia import core
from olympia.accounts.verify import IdentificationError
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    APITestClientSessionID,
    APITestClientJWT,
    TestCase,
    WithDynamicEndpoints,
    user_factory,
)
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
)
from olympia.api.tests import JWTAuthKeyTester


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


class TestJWTKeyAuthentication(JWTAuthKeyTester, TestCase):
    client_class = APITestClientJWT

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.auth = JWTKeyAuthentication()
        self.user = user_factory(read_dev_agreement=datetime.now())

    def request(self, token):
        return self.factory.get('/', HTTP_AUTHORIZATION=f'JWT {token}')

    def _create_token(self, api_key=None):
        if api_key is None:
            api_key = self.create_api_key(self.user)
        return self.create_auth_token(api_key.user, api_key.key, api_key.secret)

    def test_get_user(self):
        core.set_remote_addr('15.16.23.42')
        user, _ = self.auth.authenticate(self.request(self._create_token()))
        assert user == self.user
        assert user.last_login_ip == '15.16.23.42'
        self.assertCloseToNow(user.last_login)

    def test_authenticate_header(self):
        request = self.factory.post('/api/v4/whatever/')
        assert (
            self.auth.authenticate_header(request)
            == 'JWT realm="Access to addons.mozilla.org external API"'
        )

    def test_wrong_type_for_iat(self):
        api_key = self.create_api_key(self.user)
        # Manually create a broken payload where 'iat' is a string containing
        # a timestamp..
        issued_at = int(time.mktime(datetime.utcnow().timetuple()))
        payload = {
            'iss': api_key.key,
            'iat': str(issued_at),
            'exp': str(issued_at + settings.MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME),
        }
        token = self.encode_token_payload(payload, api_key.secret)
        core.set_remote_addr('1.2.3.4')

        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(self.request(token))
        assert ctx.exception.detail == ('Wrong type for one or more keys in payload')

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
            last_login_ip='48.15.16.23', last_login=in_the_past, deleted=True
        )

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
        jwt_decode_handler.side_effect = jwt.ExpiredSignatureError

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
            '`orig_iat` in their payload.'
        )


class TestJWTKeyAuthProtectedView(WithDynamicEndpoints, JWTAuthKeyTester, TestCase):
    client_class = APITestClientJWT

    def setUp(self):
        super().setUp()
        self.endpoint(JWTKeyAuthTestView)
        self.client.logout_api()  # just to be sure!
        self.user = user_factory(read_dev_agreement=datetime.now())

    def request(self, method, *args, **kw):
        handler = getattr(self.client, method)
        return handler(reverse('test-dynamic-endpoint'), *args, **kw)

    def jwt_request(self, token, method, *args, **kw):
        return self.request(method, HTTP_AUTHORIZATION=f'JWT {token}', *args, **kw)

    def test_get_requires_auth(self):
        res = self.request('get')
        assert res.status_code == 401, res.content

    def test_post_requires_auth(self):
        res = self.request('post', {})
        assert res.status_code == 401, res.content

    def test_can_post_with_jwt_header(self):
        api_key = self.create_api_key(self.user)
        token = self.create_auth_token(api_key.user, api_key.key, api_key.secret)
        res = self.jwt_request(token, 'post', {})

        assert res.status_code == 200, res.content
        data = json.loads(res.content)
        assert data['user_pk'] == self.user.pk

    def test_api_key_must_be_active(self):
        api_key = self.create_api_key(self.user, is_active=None)
        token = self.create_auth_token(api_key.user, api_key.key, api_key.secret)
        res = self.jwt_request(token, 'post', {})
        assert res.status_code == 401, res.content


class TestSessionIDAuthentication(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.auth = SessionIDAuthentication()
        self.factory = RequestFactory()
        self.user = user_factory(read_dev_agreement=datetime.now())
        self.update_token_mock = self.patch(
            'olympia.api.authentication.check_and_update_fxa_access_token'
        )

    def _authenticate(self, token):
        url = absolutify('/api/v4/whatever/')
        request = self.factory.post(
            url,
            HTTP_HOST='testserver',
            HTTP_AUTHORIZATION=f'Session {token}',
        )
        self.initialize_session({}, request=request)

        return self.auth.authenticate(request)

    def test_success(self):
        token = self.client.create_session(self.user)
        user, _ = self._authenticate(token)
        assert user == self.user
        self.update_token_mock.assert_called()

    def test_authenticate_header(self):
        request = self.factory.post('/api/v4/whatever/')
        assert self.auth.authenticate_header(request) == (
            'Session realm='
            '"Access to addons.mozilla.org internal API with session key"'
        )

    def test_wrong_header_only_prefix(self):
        request = self.factory.post(
            '/api/v4/whatever/',
            HTTP_AUTHORIZATION=SessionIDAuthentication.auth_header_prefix,
        )
        with self.assertRaises(AuthenticationFailed) as exp:
            self.auth.authenticate(request)
        assert exp.exception.detail['code'] == 'ERROR_INVALID_HEADER'
        assert exp.exception.detail['detail'] == (
            'Invalid Authorization header. No credentials provided.'
        )

    def test_wrong_header_too_many_spaces(self):
        request = self.factory.post(
            '/api/v4/whatever/',
            HTTP_AUTHORIZATION='{} foo bar'.format(
                SessionIDAuthentication.auth_header_prefix
            ),
        )
        with self.assertRaises(AuthenticationFailed) as exp:
            self.auth.authenticate(request)
        assert exp.exception.detail['code'] == 'ERROR_INVALID_HEADER'
        assert exp.exception.detail['detail'] == (
            'Invalid Authorization header. '
            'Credentials string should not contain spaces.'
        )

    def test_no_token(self):
        request = self.factory.post('/api/v4/whatever/')
        self.auth.authenticate(request) is None
        self.update_token_mock.assert_not_called()

    def test_still_valid_token(self):
        not_so_old_date = datetime.now() - timedelta(
            seconds=settings.SESSION_COOKIE_AGE - 30
        )
        with freeze_time(not_so_old_date):
            token = self.client.create_session(self.user)
        assert self._authenticate(token)[0] == self.user
        self.update_token_mock.assert_called()

    def test_bad_token(self):
        token = 'garbage'
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_user_id_is_none(self):
        token = self.client.create_session(self.user, _auth_user_id=None)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_user_deleted(self):
        self.user.delete()
        token = self.client.create_session(self.user)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_invalid_user_not_found(self):
        token = self.client.create_session(self.user, _auth_user_id=-1)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_invalid_user_other_user(self):
        user2 = user_factory(read_dev_agreement=datetime.now())
        token = self.client.create_session(self.user, _auth_user_id=user2.pk)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_wrong_auth_id(self):
        token = self.client.create_session(self.user)
        self.user.update(auth_id=self.user.auth_id + 42)
        with self.assertRaises(AuthenticationFailed) as exp:
            self._authenticate(token)
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Valid user session not found matching the provided session key.'
        )
        self.update_token_mock.assert_not_called()

    def test_fxa_access_token_validity_token_invalid(self):
        self.update_token_mock.side_effect = IdentificationError
        token = self.client.create_session(self.user)
        with self.assertRaises(AuthenticationFailed) as exp:
            assert self.user == self._authenticate(token)[0]
        assert exp.exception.detail['code'] == 'ERROR_AUTHENTICATION_EXPIRED'
        assert exp.exception.detail['detail'] == (
            'Access token refresh failed; user needs to login to FxA again.'
        )
