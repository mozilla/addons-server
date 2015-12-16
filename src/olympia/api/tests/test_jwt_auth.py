from datetime import datetime, timedelta
import json

from django.conf import settings
from django.test import RequestFactory

import jwt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework_jwt.settings import api_settings

from olympia.amo.tests import TestCase, WithDynamicEndpoints
from olympia.api.jwt_auth import handlers
from olympia.api.jwt_auth.views import JWTKeyAuthentication, JWTProtectedView
from olympia.api.models import APIKey, SYMMETRIC_JWT_TYPE
from olympia.users.models import UserProfile


class ProtectedView(JWTProtectedView):
    """
    This is an example of a view that would be protected by JWT token auth.
    """
    def get(self, request):
        return Response('some get response')

    def post(self, request):
        return Response({'user_pk': request.user.pk})


class JWTAuthTester(TestCase):

    def create_api_key(self, user, key='some-user-key', is_active=True,
                       secret='some-shared-secret', **kw):
        return APIKey.objects.create(type=SYMMETRIC_JWT_TYPE,
                                     user=user, key=key, secret=secret,
                                     is_active=is_active, **kw)

    def auth_token_payload(self, user, issuer):
        jwt_payload_handler = api_settings.JWT_PAYLOAD_HANDLER
        return jwt_payload_handler(user, issuer)

    def encode_token_payload(self, payload, secret):
        jwt_encode_handler = api_settings.JWT_ENCODE_HANDLER
        return jwt_encode_handler(payload, secret)

    def create_auth_token(self, user, issuer, secret):
        payload = self.auth_token_payload(user, issuer)
        return self.encode_token_payload(payload, secret)


class TestJWTProtectedView(WithDynamicEndpoints, JWTAuthTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTProtectedView, self).setUp()
        self.endpoint(ProtectedView)
        self.client.logout()  # just to be sure!
        self.user = UserProfile.objects.get(email='del@icio.us')

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
        api_key = self.create_api_key(self.user, is_active=False)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)
        res = self.jwt_request(token, 'post', {})
        assert res.status_code == 401, res.content


class TestJWTAuthHandlers(JWTAuthTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTAuthHandlers, self).setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_decode_unknown_issuer(self):
        token = self.create_auth_token(self.user, 'non-existant-issuer',
                                       'some-secret')
        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler(token)

        assert ctx.exception.message == 'unknown JWT issuer'

    def test_decode_token_without_issuer(self):
        payload = self.auth_token_payload(self.user, 'some-issuer')
        del payload['iss']
        token = self.encode_token_payload(payload, 'some-secret')
        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler(token)

        assert ctx.exception.message == 'invalid JWT'

    def test_decode_garbage_token(self):
        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler('}}garbage{{')

        assert ctx.exception.message == 'Not enough segments'

    def test_decode_invalid_non_ascii_token(self):
        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler(u'Ivan Krsti\u0107')

        assert ctx.exception.message == 'Not enough segments'

    def test_incorrect_signature(self):
        api_key = self.create_api_key(self.user)
        token = self.create_auth_token(api_key.user, api_key.key,
                                       api_key.secret)

        decoy_api_key = self.create_api_key(
            self.user, key='another-issuer', secret='another-secret')

        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler(
                token, get_api_key=lambda **k: decoy_api_key)

        assert ctx.exception.message == 'Signature verification failed'

    def test_expired_token(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['exp'] = (datetime.utcnow() -
                          api_settings.JWT_EXPIRATION_DELTA -
                          timedelta(seconds=10))
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(jwt.ExpiredSignatureError):
            handlers.jwt_decode_handler(token)

    def test_missing_issued_at_time(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        del payload['iat']
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(jwt.MissingRequiredClaimError):
            handlers.jwt_decode_handler(token)

    def test_missing_expiration(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        del payload['exp']
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(jwt.MissingRequiredClaimError):
            handlers.jwt_decode_handler(token)

    def test_disallow_long_expirations(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['exp'] = (
            datetime.utcnow() +
            timedelta(seconds=settings.MAX_JWT_AUTH_TOKEN_LIFETIME) +
            timedelta(seconds=1)
        )
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(jwt.DecodeError) as ctx:
            handlers.jwt_decode_handler(token)

        assert ctx.exception.message == 'Declared expiration was too long'


class TestJWTKeyAuthentication(JWTAuthTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTKeyAuthentication, self).setUp()
        self.factory = RequestFactory()
        self.auth = JWTKeyAuthentication()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def request(self, token):
        return self.factory.get('/', HTTP_AUTHORIZATION='JWT {}'.format(token))

    def _create_token(self):
        api_key = self.create_api_key(self.user)
        return self.create_auth_token(api_key.user, api_key.key,
                                      api_key.secret)

    def test_get_user(self):
        user, _ = self.auth.authenticate(self.request(self._create_token()))
        assert user == self.user

    def test_unknown_issuer(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['iss'] = 'non-existant-issuer'
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self.request(token))

    def test_deleted_user(self):
        self.user.update(deleted=True)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self.request(self._create_token()))

    def test_user_has_not_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self.request(self._create_token()))
