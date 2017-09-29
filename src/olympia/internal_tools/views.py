from django.conf import settings

import olympia.core.logger
from olympia import amo
from olympia.accounts.views import LoginStartBaseView
from olympia.addons.models import Addon
from olympia.addons.views import AddonViewSet, AddonSearchView
from olympia.addons.serializers import (
    AddonSerializerWithUnlistedData, ESAddonSerializerWithUnlistedData)
from olympia.api.authentication import WebTokenAuthentication
from olympia.api.permissions import AnyOf, GroupPermission
from olympia.search.filters import (
    InternalSearchParameterFilter, SearchQueryFilter, SortingFilter)

log = olympia.core.logger.getLogger('internal_tools')


class InternalAddonSearchView(AddonSearchView):
    # AddonSearchView disables auth classes so we need to add it back.
    authentication_classes = [WebTokenAuthentication]

    # Similar to AddonSearchView but without the ReviewedContentFilter (
    # allowing unlisted, deleted, unreviewed addons to show up) and with
    # InternalSearchParameterFilter instead of SearchParameterFilter (allowing
    # to search by status).
    filter_backends = [
        SearchQueryFilter, InternalSearchParameterFilter, SortingFilter
    ]

    # Restricted to specific permissions.
    permission_classes = [
        AnyOf(GroupPermission(amo.permissions.ADMIN_TOOLS_VIEW),
              GroupPermission(amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW))]
    # Can display unlisted data.
    serializer_class = ESAddonSerializerWithUnlistedData


class InternalAddonViewSet(AddonViewSet):
    # Restricted to specific permissions.
    permission_classes = [
        AnyOf(GroupPermission(amo.permissions.ADMIN_TOOLS_VIEW),
              GroupPermission(amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW))]

    # Can display unlisted data.
    serializer_class = AddonSerializerWithUnlistedData

    def get_queryset(self):
        # Internal tools allow access to everything, including deleted add-ons.
        return Addon.unfiltered.all()


class LoginStartView(LoginStartBaseView):
    DEFAULT_FXA_CONFIG_NAME = settings.INTERNAL_FXA_CONFIG_NAME
