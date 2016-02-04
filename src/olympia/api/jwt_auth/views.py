from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_jwt.authentication import JSONWebTokenAuthentication

from olympia.api.models import APIKey


class JWTKeyAuthentication(JSONWebTokenAuthentication):
    """
    DRF authentication class for JWT header auth.

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

    def authenticate_credentials(self, payload):
        """
        Returns a verified AMO user who is active and allowed to make API
        requests.
        """
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

        return api_key.user


class JWTProtectedView(APIView):
    """
    Base class to protect any API view by way of JWT headers.

    As mentioned in the authentication class, this only verifies that the
    user is who they say they are, it does not verify that the request came
    from that user. It's like Oauth 2.0 but without any need to store
    tokens in the database (because we can just verify the JWT signature).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTKeyAuthentication]
