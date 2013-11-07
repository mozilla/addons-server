from tastypie import http

from mkt.api.authentication import (OAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import OwnerAuthorization
from mkt.api.base import CORSResource, http_error, MarketplaceModelResource
from mkt.api.resources import AppResource
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.models import Webapp
from users.models import UserProfile


class Mine(object):

    def obj_get(self, request=None, **kwargs):
        if kwargs.get('pk') == 'mine':
            kwargs['pk'] = request.amo_user.pk

        # TODO: put in acl checks for admins to get other users information.
        obj = super(Mine, self).obj_get(request=request, **kwargs)
        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise http_error(http.HttpForbidden,
                             'You do not have access to that account.')
        return obj


class AccountResource(Mine, CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get', 'patch', 'put']
        fields = ['display_name']
        list_allowed_methods = []
        queryset = UserProfile.objects.filter()
        resource_name = 'settings'


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
