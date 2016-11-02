import logging

from django.conf import settings

from olympia.access import permissions
from olympia.accounts.views import LoginBaseView, LoginStartBaseView
from olympia.addons.views import AddonSearchView
from olympia.api.authentication import JSONWebTokenAuthentication
from olympia.api.permissions import AnyOf
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
    permission_classes = [AnyOf(permissions.ADMINTOOLS,
                                permissions.REVIEWERADMINTOOLS)]


class LoginStartView(LoginStartBaseView):
    DEFAULT_FXA_CONFIG_NAME = settings.INTERNAL_FXA_CONFIG_NAME


class LoginView(LoginBaseView):
    DEFAULT_FXA_CONFIG_NAME = settings.INTERNAL_FXA_CONFIG_NAME
