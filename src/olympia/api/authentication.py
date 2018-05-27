from django.conf import settings
from django.core import signing
from django.utils.crypto import constant_time_compare
from django.utils.encoding import smart_text
from django.utils.translation import ugettext

import jwt

from rest_framework import exceptions
from rest_framework.authentication import (
    BaseAuthentication, get_authorization_header)
from rest_framework_jwt.authentication import JSONWebTokenAuthentication

import olympia.core.logger

from olympia import core
from olympia.api import jwt_auth
from olympia.api.models import APIKey
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.api.authentication')


class WebTokenAuthentication(BaseAuthentication):
    """
    DRF authentication class for our internal auth API tokens (i.e. not
    external clients using API keys - see JWTKeyAuthentication for that).

    Clients should authenticate by passing the token key in the "Authorization"
    HTTP header, prepended with the "Bearer" prefix. For example:

        Authorization: Bearer eyJhbGciOiAiSFMyNTYiLCAidHlwIj
    """
    www_authenticate_realm = 'api'
    auth_header_prefix = 'Bearer'
    salt = 'olympia.api.auth'

    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response, or `None` if the
        authentication scheme should return `403 Permission Denied` responses.
        """
        return '{0} realm="{1}"'.format(
            self.auth_header_prefix.lower(), self.www_authenticate_realm)

    def get_token_value(self, request):
        auth_header = get_authorization_header(request).split()
        expected_header_prefix = self.auth_header_prefix.lower()

        if not auth_header or (
                smart_text(auth_header[0].lower()) != expected_header_prefix):
            return None

        if len(auth_header) == 1:
            msg = {
                'detail': ugettext('Invalid Authorization header. '
                                   'No credentials provided.'),
                'code': 'ERROR_INVALID_HEADER'
            }
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth_header) > 2:
            msg = {
                'detail': ugettext('Invalid Authorization header. Credentials '
                                   'string should not contain spaces.'),
                'code': 'ERROR_INVALID_HEADER',
            }
            raise exceptions.AuthenticationFailed(msg)

        return auth_header[1]

    def authenticate(self, request):
        """
        Returns a two-tuple of `User` and token if a valid tolen has been
        supplied. Otherwise returns `None`.

        Raises AuthenticationFailed if a token was specified but it's invalid
        in some way (expired signature, invalid token, etc.)
        """
        token = self.get_token_value(request)
        if token is None:
            # No token specified, skip this authentication method.
            return None
        # Proceed.
        return self.authenticate_token(token)

    def authenticate_token(self, token):
        try:
            payload = signing.loads(
                token, salt=self.salt,
                max_age=settings.SESSION_COOKIE_AGE or None)
        except signing.SignatureExpired:
            msg = {
                'detail': ugettext('Signature has expired.'),
                'code': 'ERROR_SIGNATURE_EXPIRED',
            }
            raise exceptions.AuthenticationFailed(msg)
        except signing.BadSignature:
            msg = {
                'detail': ugettext('Error decoding signature.'),
                'code': 'ERROR_DECODING_SIGNATURE'
            }
            raise exceptions.AuthenticationFailed(msg)

        # We have a valid token, try to find the corresponding user.
        user = self.authenticate_credentials(payload)

        return (user, token)

    def authenticate_credentials(self, payload):
        """
        Return a non-deleted user that matches the payload's user id.

        Mimic what our UserAndAddrMiddleware and django's get_user() do when
        authenticating, because otherwise that behaviour would be missing in
        the API since API auth happens after the middleware process request
        phase.
        """
        if 'user_id' not in payload:
            log.info('No user_id in token payload {}'.format(payload))
            raise exceptions.AuthenticationFailed()
        try:
            user = UserProfile.objects.filter(deleted=False).get(
                pk=payload['user_id'])
        except UserProfile.DoesNotExist:
            log.info('User not found from token payload {}'.format(payload))
            raise exceptions.AuthenticationFailed()

        # Check get_session_auth_hash like django's get_user() does.
        session_auth_hash = user.get_session_auth_hash()
        payload_auth_hash = payload.get('auth_hash', '')
        if not constant_time_compare(payload_auth_hash, session_auth_hash):
            log.info('User tried to authenticate with invalid auth hash in'
                     'payload {}'.format(payload))
            raise exceptions.AuthenticationFailed()

        # Set user in thread like UserAndAddrMiddleware does.
        core.set_user(user)
        return user


class JWTKeyAuthentication(JSONWebTokenAuthentication):
    """
    DRF authentication class for JWT header auth with API keys.

    This extends the django-rest-framework-jwt auth class to get the
    shared JWT secret from our APIKey database model. Each user (an add-on
    developer) can have one or more API keys. The JWT is issued with their
    public ID and is signed with their secret.

    **IMPORTANT**

    Please note that unlike typical JWT usage, this authenticator only
    signs and verifies that the user is who they say they are. It does
    not sign and verify the *entire request*. In other words, when you use
    this authentication method you cannot prove that the request was made
    by the authenticated user.
    """

    def authenticate(self, request):
        """
        Returns a two-tuple of `User` and token if a valid signature has been
        supplied using JWT-based authentication.  Otherwise returns `None`.

        Copied from rest_framework_jwt BaseJSONWebTokenAuthentication, with
        the decode_handler changed to our own - because we don't want that
        decoder to be the default one in settings - and logging added.
        """
        jwt_value = self.get_jwt_value(request)
        if jwt_value is None:
            return None

        try:
            payload = jwt_auth.jwt_decode_handler(jwt_value)
        except Exception as exc:
            try:
                # Log all exceptions
                log.info('JWTKeyAuthentication failed; '
                         'it raised %s (%s)', exc.__class__.__name__, exc)
                # Re-raise to deal with them properly.
                raise exc
            except jwt.ExpiredSignature:
                msg = ugettext('Signature has expired.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.DecodeError:
                msg = ugettext('Error decoding signature.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.InvalidTokenError:
                msg = ugettext('Invalid JWT Token.')
                raise exceptions.AuthenticationFailed(msg)
            # Note: AuthenticationFailed can also be raised directly from our
            # jwt_decode_handler.

        user = self.authenticate_credentials(payload)
        return (user, jwt_value)

    def authenticate_credentials(self, payload):
        """
        Returns a verified AMO user who is active and allowed to make API
        requests.
        """
        if 'orig_iat' in payload:
            msg = ("API key based tokens are not refreshable, don't include "
                   "`orig_iat` in their payload.")
            raise exceptions.AuthenticationFailed(msg)
        try:
            api_key = APIKey.get_jwt_key(key=payload['iss'])
        except APIKey.DoesNotExist:
            msg = 'Invalid API Key.'
            raise exceptions.AuthenticationFailed(msg)

        if api_key.user.deleted:
            msg = 'User account is disabled.'
            raise exceptions.AuthenticationFailed(msg)
        if not api_key.user.read_dev_agreement:
            msg = 'User has not read developer agreement.'
            raise exceptions.AuthenticationFailed(msg)

        core.set_user(api_key.user)
        return api_key.user

    def get_jwt_value(self, request):
        """
        Get the JWT token from the authorization header.

        Copied from upstream's implementation but uses a hardcoded 'JWT'
        prefix in order to be isolated from JWT_AUTH_HEADER_PREFIX setting
        which is used for the non-api key auth above.
        """
        auth = get_authorization_header(request).split()
        auth_header_prefix = 'jwt'  # JWT_AUTH_HEADER_PREFIX.lower()

        if not auth or smart_text(auth[0].lower()) != auth_header_prefix:
            return None

        if len(auth) == 1:
            msg = ugettext('Invalid Authorization header. '
                           'No credentials provided.')
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = ugettext('Invalid Authorization header. Credentials string '
                           'should not contain spaces.')
            raise exceptions.AuthenticationFailed(msg)

        return auth[1]
