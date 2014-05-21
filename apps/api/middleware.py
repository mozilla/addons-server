from django.conf import settings
from django.contrib.auth.models import AnonymousUser

import commonware.log
import waffle

from users.models import UserProfile

from .models import Access
from .oauth import OAuthServer


log = commonware.log.getLogger('z.api')


class RestOAuthMiddleware(object):
    """
    This is based on https://github.com/amrox/django-tastypie-two-legged-oauth
    with permission.
    """

    def process_request(self, request):
        # Do not process the request if the flag is off.
        if not waffle.switch_is_active('drf'):
            return

        path_ = request.get_full_path()
        try:
            _, lang, platform, api, rest = path_.split('/', 4)
        except ValueError:
            return
        # For now we only want these to apply to the API.
        if not api.lower() == 'api':
            return

        if not settings.SITE_URL:
            raise ValueError('SITE_URL is not specified')

        # Set up authed_from attribute.
        if not hasattr(request, 'authed_from'):
            request.authed_from = []

        auth_header_value = request.META.get('HTTP_AUTHORIZATION')
        if (not auth_header_value and
            'oauth_token' not in request.META['QUERY_STRING']):
            self.user = AnonymousUser()
            log.info('No HTTP_AUTHORIZATION header')
            return

        # Set up authed_from attribute.
        auth_header = {'Authorization': auth_header_value}
        method = getattr(request, 'signed_method', request.method)
        oauth = OAuthServer()

        # Only 2-legged OAuth scenario.
        log.info('Trying 2 legged OAuth')
        try:
            valid, oauth_request = oauth.verify_request(
                request.build_absolute_uri(),
                method, headers=auth_header,
                require_resource_owner=False)
        except ValueError:
            log.error('ValueError on verifying_request', exc_info=True)
            return
        if not valid:
            log.error(u'Cannot find APIAccess token with that key: %s'
                      % oauth.attempted_key)
            return
        uid = Access.objects.filter(
            key=oauth_request.client_key).values_list(
                'user_id', flat=True)[0]
        request.amo_user = UserProfile.objects.select_related(
            'user').get(pk=uid)
        request.user = request.amo_user

        # But you cannot have one of these roles.
        denied_groups = set(['Admins'])
        roles = set(request.amo_user.groups.values_list('name', flat=True))
        if roles and roles.intersection(denied_groups):
            log.info(u'Attempt to use API with denied role, user: %s'
                     % request.amo_user.pk)
            # Set request attributes back to None.
            request.user = request.amo_user = None
            return

        if request.user:
            request.authed_from.append('RestOAuth')

        log.info('Successful OAuth with user: %s' % request.user)
