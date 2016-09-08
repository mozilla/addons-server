import logging

from rest_framework.views import APIView, Response


from olympia.accounts.views import LoginBaseView, LoginStartBaseView
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


class LoginStartView(LoginStartBaseView):
    FXA_CONFIG_NAME = 'internal'


class LoginView(LoginBaseView):
    FXA_CONFIG_NAME = 'internal'
