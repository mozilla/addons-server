import logging

from django.conf import settings
from django.http import HttpResponseRedirect

from rest_framework.views import APIView, Response


from olympia.accounts.helpers import generate_fxa_state, fxa_login_url
from olympia.accounts.views import (
    add_api_token_to_response, update_user, with_user, ERROR_NO_USER)
from olympia.addons.views import AddonSearchView
from olympia.api.authentication import JSONWebTokenAuthentication
from olympia.api.permissions import AnyOf, GroupPermission
from olympia.search.filters import (
    InternalSearchParameterFilter, SearchQueryFilter, SortingFilter)

log = logging.getLogger('internal_tools')


class InternalAddonSearchView(AddonSearchView):
    # AddonSearchView disables auth classes so we need to add it back.
    authentication_classes = [JSONWebTokenAuthentication]

    # Similar to AddonSearchView but without the PublicContentFilter and with
    # InternalSearchParameterFilter instead of SearchParameterFilter to allow
    # searching by status.
    filter_backends = [
        SearchQueryFilter, InternalSearchParameterFilter, SortingFilter
    ]

    # Restricted to specific permissions.
    permission_classes = [AnyOf(GroupPermission('AdminTools', 'View'),
                                GroupPermission('ReviewerAdminTools', 'View'))]


class LoginStart(APIView):

    def get(self, request):
        request.session.setdefault('fxa_state', generate_fxa_state())
        return HttpResponseRedirect(
            fxa_login_url(
              config=settings.FXA_CONFIG['internal'],
              state=request.session['fxa_state'],
              next_path=request.GET.get('to'),
              action='signin'))


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

    def options(self, request):
        return Response()
