from mkt.api.authentication import (OAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import OwnerAuthorization
from mkt.api.resources import AppResource
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.models import Webapp


class InstalledResource(AppResource):

    class Meta(AppResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        resource_name = 'installed/mine'
        slug_lookup = None

    def obj_get_list(self, request=None, **kwargs):
        return Webapp.objects.no_cache().filter(
            installed__user=request.amo_user,
            installed__install_type=INSTALL_TYPE_USER)
