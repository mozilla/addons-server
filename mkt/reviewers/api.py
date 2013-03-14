from amo.urlresolvers import reverse

from mkt.api.authentication import (OAuthAuthentication,
                                    PermissionAuthorization)
from mkt.api.base import MarketplaceResource
from mkt.reviewers.utils import AppsReviewing


class Wrapper(object):

    def __init__(self, pk):
        self.pk = pk


class ReviewingResource(MarketplaceResource):

    class Meta:
        authentication = OAuthAuthentication()
        authorization = PermissionAuthorization('Apps', 'Review')
        list_allowed_methods = ['get']
        resource_name = 'reviewing'

    def get_resource_uri(self, bundle):
        return reverse('api_dispatch_detail',
                       kwargs={'api_name': 'apps', 'resource_name': 'app',
                               'pk': bundle.obj.pk})

    def obj_get_list(self, request, **kwargs):
        return [Wrapper(r['app'].pk)
                for r in AppsReviewing(request).get_apps()]
