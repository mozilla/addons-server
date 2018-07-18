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
from calendar import timegm
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

import jwt

from rest_framework import exceptions
from rest_framework_jwt.settings import api_settings

import olympia.core.logger

from olympia.api.models import APIKey


log = olympia.core.logger.getLogger('z.jwt')


def jwt_decode_handler(token, get_api_key=APIKey.get_jwt_key):
    """Decodes a JWT token."""
    # If you raise AuthenticationFailed from this method, its value will
    # be displayed to the client. Be careful not to reveal anything
    # sensitive. When you raise other exceptions, the user will see
    # a generic failure message.
    token_data = jwt.decode(
        token,
        options={
            'verify_signature': False,
            'verify_exp': False,
            'verify_nbf': False,
            'verify_iat': False,
            'verify_aud': False,
        },
    )

    if 'iss' not in token_data:
        log.info('No issuer in JWT auth token: {}'.format(token_data))
        raise exceptions.AuthenticationFailed(
            detail='JWT iss (issuer) claim is missing.'
        )

    try:
        api_key = get_api_key(key=token_data['iss'])
    except ObjectDoesNotExist as exc:
        log.info('No API key for JWT issuer: {}'.format(token_data['iss']))
        raise exceptions.AuthenticationFailed(
            detail='Unknown JWT iss (issuer).'
        )

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
        now = timegm(datetime.utcnow().utctimetuple())

        payload = jwt.decode(
            token,
            api_key.secret,
            options=options,
            leeway=api_settings.JWT_LEEWAY,
            algorithms=[api_settings.JWT_ALGORITHM],
        )

        # Verify clock skew for future iat-values pyjwt removed that check in
        # https://github.com/jpadilla/pyjwt/pull/252/
        # `verify_iat` is still in options because pyjwt still validates
        # that `iat` is a proper number.
        if int(payload['iat']) > (now + api_settings.JWT_LEEWAY):
            raise jwt.InvalidIssuedAtError(
                'Issued At claim (iat) cannot be in the future.'
            )
    except jwt.MissingRequiredClaimError as exc:
        log.info(
            u'Missing required claim during JWT authentication: '
            u'{e.__class__.__name__}: {e}'.format(e=exc)
        )
        raise exceptions.AuthenticationFailed(
            detail=u'Invalid JWT: {}.'.format(exc)
        )
    except jwt.InvalidIssuedAtError as exc:
        log.info(
            u'Invalid iat during JWT authentication: '
            u'{e.__class__.__name__}: {e}'.format(e=exc)
        )
        raise exceptions.AuthenticationFailed(
            detail='JWT iat (issued at time) is invalid. Make sure your '
            'system clock is synchronized with something like TLSdate.'
        )
    except Exception as exc:
        log.warning(
            u'Unhandled exception during JWT authentication: '
            u'{e.__class__.__name__}: {e}'.format(e=exc)
        )
        raise

    max_jwt_auth_token_lifetime = settings.MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME
    if payload['exp'] - payload['iat'] > max_jwt_auth_token_lifetime:
        log.info(
            'JWT auth: expiration is too long; '
            'iss={iss}, iat={iat}, exp={exp}'.format(**payload)
        )
        raise exceptions.AuthenticationFailed(
            detail='JWT exp (expiration) is too long.'
        )

    return payload
