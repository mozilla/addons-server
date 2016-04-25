import logging
from base64 import urlsafe_b64encode
from urllib import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url

from rest_framework.views import APIView, Response


from olympia.accounts.helpers import generate_fxa_state
from olympia.accounts.views import (
    add_api_token_to_response, update_user, with_user, ERROR_NO_USER)
from olympia.addons.views import AddonSearchView
from olympia.api.authentication import JSONWebTokenAuthentication
from olympia.api.permissions import AnyOf, GroupPermission
from olympia.search.filters import SearchQueryFilter, SortingFilter

log = logging.getLogger('internal_tools')


class InternalAddonSearchView(AddonSearchView):
    # AddonSearchView disables auth classes so we need to add it back.
    authentication_classes = [JSONWebTokenAuthentication]

    # Similar to AddonSearchView but without the PublicContentFilter.
    filter_backends = [SearchQueryFilter, SortingFilter]

    # Restricted to specific permissions.
    permission_classes = [AnyOf(GroupPermission('AdminTools', 'View'),
                                GroupPermission('ReviewerAdminTools', 'View'))]


class LoginStart(APIView):

    def get(self, request):
        config = settings.FXA_CONFIG['internal']
        request.session.setdefault('fxa_state', generate_fxa_state())
        state = request.session['fxa_state']
        next_path = request.GET.get('to')
        if next_path and is_safe_url(next_path):
            state += ':' + urlsafe_b64encode(next_path).rstrip('=')
        query = {
            'client_id': config['client_id'],
            'redirect_uri': config['redirect_uri'],
            'scope': config['scope'],
            'state': state,
        }
        return HttpResponseRedirect('{host}/authorization?{query}'.format(
            host=config['oauth_host'],
            query=urlencode(query)))


class LoginView(APIView):

    @with_user(format='json', config='internal')
    def post(self, request, user, identity, next_path):
        if user is None:
            return Response({'error': ERROR_NO_USER}, status=422)
        else:
            update_user(user, identity)
            response = Response({'email': identity['email']})
            add_api_token_to_response(response, user, set_cookie=False)
            log.info('Logging in user {} from FxA'.format(user))
            return response
