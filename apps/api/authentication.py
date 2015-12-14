from functools import partial

import commonware.log
from piston.authentication.oauth import OAuthAuthentication, views
from rest_framework.authentication import BaseAuthentication

from django.contrib.auth.models import AnonymousUser
from django.shortcuts import render

from access.middleware import ACLMiddleware
from users.models import UserProfile
from zadmin import jinja_for_django


# This allows the views in piston.authentication.oauth to cope with
# Jinja2 templates as opposed to Django templates.
# Piston view passes: template, context, request_context
def jfd(a, b, c):
    return jinja_for_django(a, b, context_instance=c)
views.render_to_response = jfd


log = commonware.log.getLogger('z.api')


class RestOAuthAuthentication(BaseAuthentication):
    www_authenticate_realm = ''

    def authenticate(self, request):
        # Most of the work here is in the RestOAuthMiddleware.
        if (getattr(request._request, 'user', None) and
                'RestOAuth' in getattr(request._request, 'authed_from', [])):
            request.user = request._request.user
            return request.user, None

    def authenticate_header(self, request):
        return 'OAuth realm="%s"' % self.www_authenticate_realm


class AMOOAuthAuthentication(OAuthAuthentication):
    """^^^MOO!!!  Adds user to the request object."""

    def is_authenticated(self, request):
        if request.user and request.user.is_authenticated():
            return True

        # To avoid patching django-piston, use a partial to cope with
        # piston not sending in request when called later.
        self.challenge = partial(self._challenge, request=request)

        # Authenticate the user using Piston, rv will be True or False
        # depending upon how it went.
        rv = super(AMOOAuthAuthentication, self).is_authenticated(request)

        if rv and request.user:
            # The user is there, but we need to alter the user to be
            # a user specified in the request. Specifically chose this
            # term to avoid conflict with user, which could be used elsewhere.
            if self.two_legged and 'authenticate_as' in request.REQUEST:
                pk = request.REQUEST.get('authenticate_as')
                try:
                    profile = UserProfile.objects.get(pk=pk)
                except UserProfile.DoesNotExist:
                    log.warning('Cannot find user: %s' % pk)
                    return False

                if profile.deleted or profile.confirmationcode:
                    log.warning('Tried to use deleted or unconfirmed user: %s'
                                % pk)
                    return False

                log.info('Authenticating as: %s' % pk)
                request.user = profile

            # If that worked and request.user got set, setup AMO specific bits.
            ACLMiddleware().process_request(request)
        else:
            # The piston middleware could find a consumer, but no
            # user on that consumer. If it does it returns True, but
            # request.user is None, which then blows up other things.
            request.user = AnonymousUser()
            return False

        return rv

    def _challenge(self, request):
        response = render(request, 'piston/oauth/challenge.html',
                          status=401)
        response['WWW-Authenticate'] = 'OAuth realm="API"'
        return response
