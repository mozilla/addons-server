import json
from urlparse import urljoin

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

import commonware.log
import oauth2
from tastypie import http
from tastypie.authentication import Authentication
from tastypie.authorization import Authorization

from access import acl
from access.middleware import ACLMiddleware
from mkt.api.models import Access

log = commonware.log.getLogger('z.api')


class OwnerAuthorization(Authorization):

    def is_authorized(self, request, object=None):
        # There is no object being passed, so we'll assume it's ok
        if not object:
            return True
        # There is no request user or no user on the object.
        if not request.amo_user:
            return False

        return self.check_owner(request, object)

    def check_owner(self, request, object):
        if not object.user:
            return False
        # If the user on the object and the amo_user match, we are golden.
        return object.user.pk == request.amo_user.pk


class AppOwnerAuthorization(OwnerAuthorization):

    def check_owner(self, request, object):
        # If the user on the object and the amo_user match, we are golden.
        return object.authors.filter(user__id=request.amo_user.pk)


class PermissionAuthorization(Authorization):

    def __init__(self, app, action, *args, **kw):
        self.app, self.action = app, action

    def is_authorized(self, request, object=None):
        if acl.action_allowed(request, self.app, self.action):
            log.info('Permission authorization failed')
            return True
        return False


class OAuthError(RuntimeError):
    def __init__(self, message='OAuth error occured.'):
        self.message = message


errors = {
    'headers': 'Error with OAuth headers',
    'roles': 'Cannot be a user with roles.',
    'terms': 'Terms of service not accepted.',
}


class MarketplaceAuthentication(Authentication):
    """
    This is based on https://github.com/amrox/django-tastypie-two-legged-oauth
    with permission.
    """

    def __init__(self, realm='API'):
        self.realm = realm

    def _error(self, reason):
        return http.HttpUnauthorized(content=json.dumps({'reason':
                                                         errors[reason]}))

    def _header(self, request):
        return request.META.get('HTTP_AUTHORIZATION', None)

    def is_authenticated(self, request, **kwargs):
        auth_header_value = self._header(request)
        oauth_server, oauth_request = initialize_oauth_server_request(request)

        try:
            key = get_oauth_consumer_key_from_header(auth_header_value)
            if not key:
                return None

            consumer = Access.objects.get(key=key)
            oauth_server.verify_request(oauth_request, consumer, None)
            # Set the current user to be the consumer owner.
            request.user = consumer.user

        except Access.DoesNotExist:
            log.error(u'Cannot find APIAccess token with that key: %s' % key)
            request.user = AnonymousUser()
            return self._error('headers')

        except:
            log.error(u'Error getting OAuth headers', exc_info=True)
            request.user = AnonymousUser()
            return self._error('headers')

        ACLMiddleware().process_request(request)

        # Do not allow access without agreeing to the dev agreement.
        if not request.amo_user.read_dev_agreement:
            log.info(u'Attempt to use API without dev agreement: %s'
                     % request.amo_user.pk)
            return self._error('terms')

        # But you cannot have one of these roles.
        denied_groups = set(['Admins'])
        roles = set(request.amo_user.groups.values_list('name', flat=True))
        if roles and roles.intersection(denied_groups):
            log.info(u'Attempt to use API with denied role, user: %s'
                     % request.amo_user.pk)
            return self._error('roles')

        return True


class OptionalAuthentication(MarketplaceAuthentication):
    """
    Like MarketplaceAuthentication, but doesn't require there to be
    authentication headers. If no headers are provided, just continue
    as an anonymous user.
    """

    def is_authenticated(self, request, **kw):
        auth_header_value = self._header(request)
        if not auth_header_value:
            request.user = AnonymousUser()
            return True

        return (super(OptionalAuthentication, self)
                .is_authenticated(request, **kw))


def initialize_oauth_server_request(request):
    """
    OAuth initialization.
    """

    # Since 'Authorization' header comes through as 'HTTP_AUTHORIZATION',
    # convert it back.
    auth_header = {}
    if 'HTTP_AUTHORIZATION' in request.META:
        auth_header = {'Authorization': request.META.get('HTTP_AUTHORIZATION')}

    url = urljoin(settings.SITE_URL, request.path)

    # Note: we are only signing using the QUERY STRING. We are not signing the
    # body yet. According to the spec we should be including an oauth_body_hash
    # as per:
    #
    # http://oauth.googlecode.com/svn/spec/ext/body_hash/1.0/drafts/1/spec.html
    #
    # There is no support in python-oauth2 for this yet. There is an
    # outstanding pull request for this:
    #
    # https://github.com/simplegeo/python-oauth2/pull/110
    #
    # Or time to move to a better OAuth implementation.
    oauth_request = oauth2.Request.from_request(
            request.method, url, headers=auth_header,
            query_string=request.META['QUERY_STRING'])
    oauth_server = oauth2.Server(signature_methods={
        'HMAC-SHA1': oauth2.SignatureMethod_HMAC_SHA1()
        })
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
