from base64 import urlsafe_b64encode
from urllib import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url

from rest_framework.views import APIView

from olympia.accounts.helpers import generate_fxa_state
from olympia.addons.views import AddonSearchView
from olympia.api.authentication import JSONWebTokenAuthentication
from olympia.api.permissions import AnyOf, GroupPermission
from olympia.search.filters import SearchQueryFilter, SortingFilter


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
        request.session.setdefault('fxa_state', generate_fxa_state())
        state = request.session['fxa_state']
        next_path = request.GET.get('to')
        if next_path and is_safe_url(next_path):
            state += ':' + urlsafe_b64encode(next_path).rstrip('=')
        query = {
            'client_id': settings.ADMIN_FXA_CONFIG['client_id'],
            'redirect_uri': settings.ADMIN_FXA_CONFIG['redirect_uri'],
            'scope': settings.ADMIN_FXA_CONFIG['scope'],
            'state': state,
        }
        return HttpResponseRedirect('{host}/authorization?{query}'.format(
            host=settings.ADMIN_FXA_CONFIG['oauth_host'],
            query=urlencode(query)))
