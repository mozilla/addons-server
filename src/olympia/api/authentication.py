from django.utils.translation import ugettext as _

import commonware
import jwt
from rest_framework import exceptions
from rest_framework_jwt.authentication import (
    JSONWebTokenAuthentication as UpstreamJSONWebTokenAuthentication)

from olympia import amo
from olympia.api import jwt_auth
from olympia.api.models import APIKey


log = commonware.log.getLogger('z.api.authentication')


class JSONWebTokenAuthentication(UpstreamJSONWebTokenAuthentication):
    """
    DRF authentication class for JWT header auth.

    This mimics what our ACLMiddleware does after a successful authentication,
    because otherwise that behaviour would be missing in the API since API auth
    happens after the middleware process request phase.
    """
    def authenticate_credentials(self, request):
        result = super(
            JSONWebTokenAuthentication, self).authenticate_credentials(request)
        amo.set_user(result)
        return result


class JWTKeyAuthentication(UpstreamJSONWebTokenAuthentication):
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
        except Exception, exc:
            try:
                # Log all exceptions
                log.info('JWTKeyAuthentication failed; '
                         'it raised %s (%s)', exc.__class__.__name__, exc)
                # Re-raise to deal with them properly.
                raise exc
            except jwt.ExpiredSignature:
                msg = _('Signature has expired.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.DecodeError:
                msg = _('Error decoding signature.')
                raise exceptions.AuthenticationFailed(msg)
            except jwt.InvalidTokenError:
                msg = _('Invalid JWT Token.')
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

        amo.set_user(api_key.user)
        return api_key.user
