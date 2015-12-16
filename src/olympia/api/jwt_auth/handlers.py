"""
Implementations of django-rest-framework-jwt callbacks.

AMO uses JWT tokens in a different way. Notes:
* Each add-on dev creates JWT headers using their APIKey key/secret pair.
* We do not support JWT generation in any of our API endpoints. It's up to
  developers to generate their own JWTs.
* Our JWT header auth is intended for script-to-service at the moment.
* We are not signing entire requests like you normally would with a JWT
  because the signing API needs to accept a file upload and files might be
  large.

See https://github.com/GetBlimp/django-rest-framework-jwt/ for more info.
"""
from datetime import datetime
import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

import jwt
from rest_framework_jwt.settings import api_settings

from olympia.apps.api.models import APIKey

log = logging.getLogger('z.jwt')


def jwt_payload_handler(user, issuer):
    issued_at = datetime.utcnow()
    return {
        # The JWT issuer must match the 'key' field of APIKey
        'iss': issuer,
        'iat': issued_at,
        'exp': issued_at + api_settings.JWT_EXPIRATION_DELTA,
    }


def jwt_encode_handler(payload, secret):
    token = jwt.encode(payload, secret, api_settings.JWT_ALGORITHM)
    return token.decode('utf-8')


def jwt_decode_handler(token, get_api_key=APIKey.get_jwt_key):
    token_data = jwt.decode(token, verify=False)
    if 'iss' not in token_data:
        log.info('No issuer in JWT auth token: {}'.format(token_data))
        raise jwt.DecodeError('invalid JWT')

    try:
        api_key = get_api_key(key=token_data['iss'])
    except ObjectDoesNotExist, exc:
        log.info('No API key for JWT issuer: {}'.format(token_data['iss']))
        raise jwt.DecodeError('unknown JWT issuer')

    # TODO: add nonce checking to prevent replays. bug 1213354.

    options = {
        'verify_signature': True,
        'verify_exp': True,
        'verify_nbf': False,
        'verify_iat': True,
        'verify_aud': False,
        'require_exp': True,
        'require_iat': True,
        'require_nbf': False,
    }
    try:
        payload = jwt.decode(
            token,
            api_key.secret,
            verify=True,
            options=options,
            leeway=api_settings.JWT_LEEWAY,
            algorithms=[api_settings.JWT_ALGORITHM]
        )
    except Exception, exc:
        log.info(u'Exception during JWT authentication: '
                 u'{e.__class__.__name__}: {e}'.format(e=exc))
        raise

    if payload['exp'] - payload['iat'] > settings.MAX_JWT_AUTH_TOKEN_LIFETIME:
        log.info('JWT auth: expiration is too long; '
                 'iss={iss}, iat={iat}, exp={exp}'.format(**payload))
        raise jwt.DecodeError('Declared expiration was too long')

    return payload
