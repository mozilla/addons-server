import hashlib
import hmac
import json

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User

import commonware.log
from rest_framework.authentication import BaseAuthentication
from tastypie import http
from tastypie.authentication import Authentication
import waffle

from access.middleware import ACLMiddleware
from users.models import UserProfile
from mkt.api.middleware import APIPinningMiddleware

from mkt.api.models import Access, Token, ACCESS_TOKEN
from mkt.api.oauth import OAuthServer

log = commonware.log.getLogger('z.api')


class OAuthError(RuntimeError):
    def __init__(self, message='OAuth error occured.'):
        self.message = message


errors = {
    'headers': 'Error with OAuth headers',
    'roles': 'Cannot be a user with roles.',
}


class OAuthAuthentication(Authentication):
    """
    This is based on https://github.com/amrox/django-tastypie-two-legged-oauth
    with permission.
    """

    def __init__(self, realm='API'):
        self.realm = realm

    def _error(self, reason):
        return http.HttpUnauthorized(content=json.dumps({'reason':
                                                         errors[reason]}))

    def is_authenticated(self, request, **kwargs):
        if not settings.SITE_URL:
            raise ValueError('SITE_URL is not specified')

        auth_header_value = request.META.get('HTTP_AUTHORIZATION')
        if (not auth_header_value and
            'oauth_token' not in request.META['QUERY_STRING']):
            self.user = AnonymousUser()
            log.error('No header')
            return self._error('headers')

        auth_header = {'Authorization': auth_header_value}
        method = getattr(request, 'signed_method', request.method)
        oauth = OAuthServer()
        if ('oauth_token' in request.META['QUERY_STRING'] or
            'oauth_token' in auth_header_value):
            # This is 3-legged OAuth.
            log.info('Trying 3 legged OAuth')
            try:
                valid, oauth_request = oauth.verify_request(
                    request.build_absolute_uri(),
                    method, headers=auth_header,
                    require_resource_owner=True)
            except ValueError:
                log.error('ValueError on verifying_request', exc_info=True)
                return False
            if not valid:
                log.error(u'Cannot find APIAccess token with that key: %s'
                          % oauth.attempted_key)
                return self._error('headers')
            uid = Token.objects.filter(
                token_type=ACCESS_TOKEN,
                key=oauth_request.resource_owner_key).values_list(
                    'user_id', flat=True)[0]
            request.amo_user = UserProfile.objects.select_related(
                'user').get(pk=uid)
            request.user = request.amo_user.user
        else:
            # This is 2-legged OAuth.
            log.info('Trying 2 legged OAuth')
            try:
                valid, oauth_request = oauth.verify_request(
                    request.build_absolute_uri(),
                    method, headers=auth_header,
                    require_resource_owner=False)
            except ValueError:
                log.error('ValueError on verifying_request', exc_info=True)
                return False
            if not valid:
                log.error(u'Cannot find APIAccess token with that key: %s'
                          % oauth.attempted_key)
                return self._error('headers')
            uid = Access.objects.filter(
                key=oauth_request.client_key).values_list(
                    'user_id', flat=True)[0]
            request.amo_user = UserProfile.objects.select_related(
                'user').get(pk=uid)
            request.user = request.amo_user.user
        ACLMiddleware().process_request(request)
        # We've just become authenticated, time to run the pinning middleware
        # again.
        #
        # TODO: I'd like to see the OAuth authentication move to middleware.
        request.API = True  # We can be pretty sure we are in the API.
        APIPinningMiddleware().process_request(request)

        # Persist the user's language.
        if (getattr(request, 'amo_user', None)
            and request.amo_user.lang != request.LANG):
            request.amo_user.lang = request.LANG
            request.amo_user.save()

        # But you cannot have one of these roles.
        denied_groups = set(['Admins'])
        roles = set(request.amo_user.groups.values_list('name', flat=True))
        if roles and roles.intersection(denied_groups):
            log.info(u'Attempt to use API with denied role, user: %s'
                     % request.amo_user.pk)
            return self._error('roles')

        log.info('Successful OAuth with user: %s' % request.user)
        return True


class OptionalOAuthAuthentication(OAuthAuthentication):
    """
    Like OAuthAuthentication, but doesn't require there to be
    authentication headers. If no headers are provided, just continue
    as an anonymous user.
    """

    def is_authenticated(self, request, **kw):
        auth_header_value = request.META.get('HTTP_AUTHORIZATION', None)
        if (not auth_header_value and
            'oauth_token' not in request.META['QUERY_STRING']):
            request.user = AnonymousUser()
            log.info('Successful OptionalOAuth as anonymous user')
            return True

        return (super(OptionalOAuthAuthentication, self)
                .is_authenticated(request, **kw))


class SharedSecretAuthentication(Authentication):

    def is_authenticated(self, request, **kwargs):
        header = request.META.get('HTTP_AUTHORIZATION', '').split(None, 1)
        if header and header[0].lower() == 'mkt-shared-secret':
            auth = header[1]
        elif waffle.switch_is_active('shared-secret-in-url'):
            auth = request.GET.get('_user')
        else:
            auth = ''
        if not auth:
            log.info('API request made without shared-secret auth token')
            return False
        try:
            email, hm, unique_id = str(auth).split(',')
            consumer_id = hashlib.sha1(
                email + settings.SECRET_KEY).hexdigest()
            matches = hmac.new(unique_id + settings.SECRET_KEY,
                               consumer_id, hashlib.sha512).hexdigest() == hm
            if matches:
                try:
                    request.amo_user = UserProfile.objects.select_related(
                        'user').get(email=email)
                    request.user = request.amo_user.user
                except UserProfile.DoesNotExist:
                    log.info('Auth token matches absent user (%s)' % email)
                    return False
                ACLMiddleware().process_request(request)
            else:
                log.info('Shared-secret auth token does not match')
                return False

            log.info('Successful SharedSecret with user: %s' % request.user.pk)
            return matches
        except Exception, e:
            log.info('Bad shared-secret auth data: %s (%s)', auth, e)
            return False


class RestOAuthAuthentication(BaseAuthentication, OAuthAuthentication):
    """OAuthAuthentication suitable for DRF, wraps around tastypie ones."""

    def authenticate(self, request):
        result = self.is_authenticated(request)
        if (not result or isinstance(result, http.HttpUnauthorized)
            or not request.user):
            return None
        return (request.user, None)


class RestSharedSecretAuthentication(BaseAuthentication,
                                     SharedSecretAuthentication):
    """SharedSecretAuthentication suitable for DRF."""

    def authenticate(self, request):
        result = self.is_authenticated(request)

        if not (result and request.user):
            return None
        return (request.user, None)
