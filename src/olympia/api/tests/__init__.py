from datetime import datetime, timedelta

from django.conf import settings

import jwt

from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey


class JWTAuthKeyTester:
    def create_api_key(
        self,
        user,
        key='some-user-key',
        is_active=True,
        secret='some-shared-secret',
        **kw,
    ):
        return APIKey.objects.create(
            type=SYMMETRIC_JWT_TYPE,
            user=user,
            key=key,
            secret=secret,
            is_active=is_active,
            **kw,
        )

    def auth_token_payload(self, user, issuer, issued_at=None):
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
        token = jwt.encode(payload, secret, settings.JWT_AUTH['JWT_ALGORITHM'])
        return token

    def create_auth_token(self, user, issuer, secret):
        payload = self.auth_token_payload(user, issuer)
        return self.encode_token_payload(payload, secret)
