from django.contrib.auth import get_user
from django.contrib.auth.signals import user_logged_in
from django.utils.encoding import force_str, smart_str
from django.utils.translation import gettext

import jwt
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

import olympia.core.logger
from olympia import core
from olympia.accounts.verify import (
    IdentificationError,
    check_and_update_fxa_access_token,
)
from olympia.api import jwt_auth
from olympia.api.models import APIKey
from olympia.users.models import UserProfile
from olympia.users.utils import UnsubscribeCode


log = olympia.core.logger.getLogger('z.api.authentication')


class SessionIDAuthentication(BaseAuthentication):
    """
    DRF authentication class using the session id for django sessions (i.e. not
    external clients using API keys - see JWTKeyAuthentication for that).

    Clients should authenticate by passing the session id value in the "Authorization"
    HTTP header, prepended with the "Session" prefix. For example:

        Authorization: Session eyJhbGciOiAiSFMyNTYiLCAidHlwIj
    """

    www_authenticate_realm = (
        'Access to addons.mozilla.org internal API with session key'
    )
    auth_header_prefix = 'Session'
    salt = 'olympia.api.auth'

    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response, or `None` if the
        authentication scheme should return `403 Permission Denied` responses.
        """
        return '{} realm="{}"'.format(
            self.auth_header_prefix, self.www_authenticate_realm
        )

    def get_token_value(self, request):
        auth_header = get_authorization_header(request).split()
        expected_header_prefix = self.auth_header_prefix.upper()

        if not auth_header or (
            smart_str(auth_header[0].upper()) != expected_header_prefix
        ):
            return None

        if len(auth_header) == 1:
            msg = {
                'detail': gettext(
                    'Invalid Authorization header. No credentials provided.'
                ),
                'code': 'ERROR_INVALID_HEADER',
            }
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth_header) > 2:
            msg = {
                'detail': gettext(
                    'Invalid Authorization header. Credentials string should not '
                    'contain spaces.'
                ),
                'code': 'ERROR_INVALID_HEADER',
            }
            raise exceptions.AuthenticationFailed(msg)

        return auth_header[1]

    def authenticate(self, request):
        """
        Returns a two-tuple of `User` and token if a valid token has been supplied.
        Otherwise returns `None`.

        Raises AuthenticationFailed if a token was specified but it's invalid
        in some way (expired signature, invalid token, etc.)
        """
        token = self.get_token_value(request)
        if token is None:
            # No token specified, skip this authentication method.
            return None
        # Proceed.
        return self.authenticate_credentials(request, force_str(token))

    def authenticate_credentials(self, request, token):
        # initialize session with the key from the token rather than the cookie like
        # SessionMiddleware does.
        del request.session._session_cache
        request.session._session_key = token

        # call get_user to validate the session information is good - it returns safely
        user = get_user(request)
        if not user or user.is_anonymous or user.deleted:
            log.info('User or session not found.')
            msg = {
                'detail': gettext(
                    'Valid user session not found matching the provided session key.'
                ),
                'code': 'ERROR_AUTHENTICATION_EXPIRED',
            }
            raise exceptions.AuthenticationFailed(msg)

        try:
            check_and_update_fxa_access_token(request)
        except IdentificationError:
            log.info(
                'User access token refresh failed; user needs to login to FxA again'
            )
            msg = {
                'detail': gettext(
                    'Access token refresh failed; user needs to login to FxA again.'
                ),
                'code': 'ERROR_AUTHENTICATION_EXPIRED',
            }
            raise exceptions.AuthenticationFailed(msg)

        # Set user in thread like UserAndAddrMiddleware does.
        core.set_user(user)

        return (user, token)


class JWTKeyAuthentication(BaseAuthentication):
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

    www_authenticate_realm = 'Access to addons.mozilla.org external API'
    auth_header_prefix = 'JWT'

    def authenticate_header(self, request):
        """
        Return a string to be used as the value of the `WWW-Authenticate`
        header in a `401 Unauthenticated` response, or `None` if the
        authentication scheme should return `403 Permission Denied` responses.
        """
        return '{} realm="{}"'.format(
            self.auth_header_prefix, self.www_authenticate_realm
        )

    def authenticate(self, request):
        """
        Returns a two-tuple of `User` and token if a valid signature has been
        supplied using JWT-based authentication.  Otherwise returns `None`.
        """
        jwt_value = self.get_jwt_value(request)
        if jwt_value is None:
            return None

        try:
            payload = jwt_auth.jwt_decode_handler(jwt_value)
        except Exception as exc:
            try:
                # Log all exceptions
                log.info(
                    'JWTKeyAuthentication failed; it raised %s (%s)',
                    exc.__class__.__name__,
                    exc,
                )
                # Re-raise to deal with them properly.
                raise exc
            except TypeError:
                msg = gettext('Wrong type for one or more keys in payload')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.ExpiredSignatureError:
                msg = gettext('Signature has expired.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.DecodeError:
                msg = gettext('Error decoding signature.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.InvalidTokenError:
                msg = gettext('Invalid JWT Token.')
                raise exceptions.AuthenticationFailed(msg)
            # Note: AuthenticationFailed can also be raised directly from our
            # jwt_decode_handler.

        user = self.authenticate_credentials(payload)
        # Send user_logged_in signal when JWT is used to authenticate an user.
        # Otherwise, we'd never update the last_login information for users
        # who never visit the site but do use the API to upload new add-ons.
        user_logged_in.send(
            sender=self.__class__, request=request, user=user, using_api_token=True
        )
        return (user, jwt_value)

    def authenticate_credentials(self, payload):
        """
        Returns a verified AMO user who is active and allowed to make API
        requests.
        """
        if 'orig_iat' in payload:
            msg = (
                "API key based tokens are not refreshable, don't include "
                '`orig_iat` in their payload.'
            )
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
        """
        auth = get_authorization_header(request).split()

        if not auth or smart_str(auth[0].upper()) != self.auth_header_prefix.upper():
            return None

        if len(auth) == 1:
            msg = gettext('Invalid Authorization header. No credentials provided.')
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = gettext(
                'Invalid Authorization header. Credentials string '
                'should not contain spaces.'
            )
            raise exceptions.AuthenticationFailed(msg)

        return auth[1]


class UnsubscribeTokenAuthentication(BaseAuthentication):
    """
    DRF authentication class for email unsubscribe notifications - token and
    hash should be provided in the POST data.  ONLY use this authentication for
    account notifications.
    """

    def authenticate(self, request):
        try:
            email = UnsubscribeCode.parse(
                request.data.get('token'), request.data.get('hash')
            )
            user = UserProfile.objects.get(email=email)
        except ValueError:
            raise exceptions.AuthenticationFailed(gettext('Invalid token or hash.'))
        except UserProfile.DoesNotExist:
            raise exceptions.AuthenticationFailed(gettext('Email address not found.'))
        return (user, None)
