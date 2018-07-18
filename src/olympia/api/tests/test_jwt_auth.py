from datetime import datetime, timedelta

from django.conf import settings

import jwt

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_jwt.settings import api_settings

from olympia.amo.tests import TestCase
from olympia.api import jwt_auth
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.users.models import UserProfile


class JWTAuthKeyTester(TestCase):
    def create_api_key(
        self,
        user,
        key='some-user-key',
        is_active=True,
        secret='some-shared-secret',
        **kw
    ):
        return APIKey.objects.create(
            type=SYMMETRIC_JWT_TYPE,
            user=user,
            key=key,
            secret=secret,
            is_active=is_active,
            **kw
        )

    def auth_token_payload(self, user, issuer):
        """Creates a JWT payload as a client would."""
        issued_at = datetime.utcnow()
        return {
            # The JWT issuer must match the 'key' field of APIKey
            'iss': issuer,
            'iat': issued_at,
            'exp': issued_at
            + timedelta(seconds=settings.MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME),
        }

    def encode_token_payload(self, payload, secret):
        """Encodes a JWT payload as a client would."""
        token = jwt.encode(payload, secret, api_settings.JWT_ALGORITHM)
        return token.decode('utf-8')

    def create_auth_token(self, user, issuer, secret):
        payload = self.auth_token_payload(user, issuer)
        return self.encode_token_payload(payload, secret)


class TestJWTKeyAuthDecodeHandler(JWTAuthKeyTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestJWTKeyAuthDecodeHandler, self).setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_report_unknown_issuer(self):
        token = self.create_auth_token(
            self.user, 'non-existant-issuer', 'some-secret'
        )
        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert ctx.exception.detail == 'Unknown JWT iss (issuer).'

    def test_report_token_without_issuer(self):
        payload = self.auth_token_payload(self.user, 'some-issuer')
        del payload['iss']
        token = self.encode_token_payload(payload, 'some-secret')
        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert ctx.exception.detail == 'JWT iss (issuer) claim is missing.'

    def test_decode_garbage_token(self):
        with self.assertRaises(jwt.DecodeError) as ctx:
            jwt_auth.jwt_decode_handler('}}garbage{{')

        assert str(ctx.exception) == 'Not enough segments'

    def test_decode_invalid_non_ascii_token(self):
        with self.assertRaises(jwt.DecodeError) as ctx:
            jwt_auth.jwt_decode_handler(u'Ivan Krsti\u0107')

        assert str(ctx.exception) == 'Not enough segments'

    def test_incorrect_signature(self):
        api_key = self.create_api_key(self.user)
        token = self.create_auth_token(
            api_key.user, api_key.key, api_key.secret
        )

        decoy_api_key = APIKey(  # Don't save in database, it would conflict.
            user=self.user, key=api_key.key, secret='another-secret'
        )

        with self.assertRaises(jwt.DecodeError) as ctx:
            jwt_auth.jwt_decode_handler(
                token, get_api_key=lambda **k: decoy_api_key
            )

        assert str(ctx.exception) == 'Signature verification failed'

    def test_expired_token(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['exp'] = datetime.utcnow() - timedelta(seconds=10)
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(jwt.ExpiredSignatureError):
            jwt_auth.jwt_decode_handler(token)

    def test_missing_issued_at_time(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        del payload['iat']
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert (
            ctx.exception.detail
            == 'Invalid JWT: Token is missing the "iat" claim.'
        )

    def test_invalid_issued_at_time(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)

        # Simulate clock skew...
        payload['iat'] = datetime.utcnow() + timedelta(
            seconds=settings.JWT_AUTH['JWT_LEEWAY'] + 10
        )
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert ctx.exception.detail.startswith(
            'JWT iat (issued at time) is invalid.'
        )

    def test_invalid_issued_at_time_not_number(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)

        # Simulate clock skew...
        payload['iat'] = 'thisisnotanumber'
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert ctx.exception.detail.startswith(
            'JWT iat (issued at time) is invalid.'
        )

    def test_missing_expiration(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        del payload['exp']
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert (
            ctx.exception.detail
            == 'Invalid JWT: Token is missing the "exp" claim.'
        )

    def test_disallow_long_expirations(self):
        api_key = self.create_api_key(self.user)
        payload = self.auth_token_payload(self.user, api_key.key)
        payload['exp'] = (
            datetime.utcnow()
            + timedelta(seconds=settings.MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME)
            + timedelta(seconds=1)
        )
        token = self.encode_token_payload(payload, api_key.secret)

        with self.assertRaises(AuthenticationFailed) as ctx:
            jwt_auth.jwt_decode_handler(token)

        assert ctx.exception.detail == 'JWT exp (expiration) is too long.'
