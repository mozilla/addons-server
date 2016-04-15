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
