from functools import partial

import commonware.log
from piston.authentication.oauth import OAuthAuthentication, views

from django.contrib.auth.models import AnonymousUser

from access.middleware import ACLMiddleware
from amo.decorators import json_view
from zadmin import jinja_for_django

# This allows the views in piston.authentication.oauth to cope with
# Jinja2 templates as opposed to Django templates.
# Piston view passes: template, context, request_context
jfd = lambda a, b, c: jinja_for_django(a, b, context_instance=c)
views.render_to_response = jfd


log = commonware.log.getLogger('z.api')


class MarketplaceAuth(OAuthAuthentication):
    """Adds amo_user to the request object."""

    def is_authenticated(self, request):
        if request.user and request.user.is_authenticated():
            return True

        # piston not sending in request when called later.
        self.challenge = partial(self._challenge, request=request)

        # Authenticate the user using Piston, rv will be True or False
        # depending upon how it went.
        rv = super(MarketplaceAuth, self).is_authenticated(request)
        if rv and request.user:
            # Check that consumer is valid. Not sure why piston is not
            # doing this.
            if request.consumer.status != 'accepted':
                return False

            ACLMiddleware().process_request(request)

            # Do not allow any user with any roles to use the API.
            # Just in case.
            if request.amo_user.groups.all():
                return False
        else:
            # The piston middleware could find a consumer, but no
            # user on that consumer. If it does it returns True, but
            # request.user is None, which then blows up other things.
            request.user = AnonymousUser()
            return False

        return rv

    @json_view(status_code=401)
    def _challenge(self, request):
        return {'error': 'Invalid OAuthToken.'}
