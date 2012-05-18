from urlparse import urljoin

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

import commonware.log
import oauth2
from piston.models import Consumer
from tastypie.authentication import Authentication
from tastypie.authorization import Authorization

from access.middleware import ACLMiddleware

log = commonware.log.getLogger('z.api')


class OwnerAuthorization(Authorization):

    def is_authorized(self, request, object=None):
        # There is no object being passed, so we'll assume it's ok
        if not object:
            return True
        # There is no request user or no user on the object.
        if not request.amo_user or not object.user:
            return False
        # If the user on the object and the amo_user match, we are golden.
        return object.user.pk == request.amo_user.pk

    def get_identifier(self, *args, **kwargs):
        return object.user.pk


class OAuthError(RuntimeError):
    def __init__(self, message='OAuth error occured.'):
        self.message = message


class MarketplaceAuthentication(Authentication):
    """
    This is based on https://github.com/amrox/django-tastypie-two-legged-oauth
    with permission.
    """

    def __init__(self, realm='API'):
        self.realm = realm

    def is_authenticated(self, request, **kwargs):
        oauth_server, oauth_request = initialize_oauth_server_request(request)

        try:
            auth_header_value = request.META.get('HTTP_AUTHORIZATION')
            key = get_oauth_consumer_key_from_header(auth_header_value)

            if not key:
                return None

            consumer = get_consumer(key)
            oauth_server.verify_request(oauth_request, consumer, None)
            # Set the current user to be the consumer owner.
            request.user = consumer.user

        except:
            log.error(u'Error get OAuth headers', exc_info=True)
            request.user = AnonymousUser()
            return False

        # Check that consumer is valid.
        if consumer.status != 'accepted':
            log.info(u'Consumer not accepted: %s' % consumer)
            return False

        ACLMiddleware().process_request(request)
        # Do not allow any user with any roles to use the API.
        # Just in case.
        if request.amo_user.groups.all():
            log.info(u'Attempt to use API with roles, user: %s'
                     % request.amo_user.pk)
            return False

        return True


def initialize_oauth_server_request(request):
    """
    OAuth initialization.
    """

    # Since 'Authorization' header comes through as 'HTTP_AUTHORIZATION',
    # convert it back
    auth_header = {}
    if 'HTTP_AUTHORIZATION' in request.META:
        auth_header = {'Authorization': request.META.get('HTTP_AUTHORIZATION')}

    url = urljoin(settings.SITE_URL, request.path)

    oauth_request = oauth2.Request.from_request(
            request.method, url, headers=auth_header)

    if oauth_request:
        oauth_server = oauth2.Server(signature_methods={
            # Supported signature methods
            'HMAC-SHA1': oauth2.SignatureMethod_HMAC_SHA1()
            })

    else:
        oauth_server = None

    return oauth_server, oauth_request


def get_oauth_consumer_key_from_header(auth_header_value):
    key = None

    # Process Auth Header
    if not auth_header_value:
        return None
    # Check that the authorization header is OAuth.
    if auth_header_value[:6] == 'OAuth ':
        auth_header = auth_header_value[6:]
        try:
            # Get the parameters from the header.
            header_params = oauth2.Request._split_header(auth_header)
            if 'oauth_consumer_key' in header_params:
                key = header_params['oauth_consumer_key']
        except:
            raise OAuthError('Unable to parse OAuth parameters from '
                    'Authorization header.')
    return key


def get_consumer(key):
    try:
        consumer = Consumer.objects.get(key=key)
    except Consumer.DoesNotExist:
        raise OAuthError('Invalid consumer')

    # This insanity prevents a hash error inside oauth2.
    consumer.key = str(consumer.key)
    consumer.secret = str(consumer.secret)
    return consumer
