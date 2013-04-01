from tastypie.authorization import ReadOnlyAuthorization

from mkt import regions
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.resources import AppResource, CategoryResource
from mkt.webapps.models import Webapp


class HomepageResource(CORSResource, MarketplaceResource):

    class Meta(MarketplaceResource):
        resource_name = 'page'
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        authorization = ReadOnlyAuthorization()
        object_class = dict

    def get_resource_uri(self, bundle):
        return None

    def get_list(self, request, **kwargs):
        region = getattr(request, 'REGION', regions.WORLDWIDE)
        kw = self.lookup_device(request.GET.get('dev', ''))

        cat = CategoryResource()
        featured = Webapp.featured(region=region, cat=None,
                                   limit=9 if kw['mobile'] else 12, **kw)

        return self.create_response(request, {
            'categories': cat.dehydrate_objects(cat.obj_get_list()),
            'featured': AppResource().dehydrate_objects(featured)
        })

    def lookup_device(self, device):
        return {'mobile': device in ['android', 'firefoxos'],
                'tablet': device == 'android',
                'gaia': device == 'firefoxos'}
