from tastypie.authorization import ReadOnlyAuthorization
from tastypie.bundle import Bundle

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

        featured = Webapp.featured(region=region, cat=None,
                                   limit=9 if kw['mobile'] else 12, **kw)
        featured = [AppResource().full_dehydrate(Bundle(obj=app)).data
                    for app in featured]

        cat = CategoryResource()
        categories = [cat.full_dehydrate(Bundle(obj=c)).data
                      for c in cat.obj_get_list()]

        return self.create_response(request, {'categories': categories,
                                              'featured': featured})

    def lookup_device(self, device):
        return {'mobile': device in ['android', 'firefoxos'],
                'tablet': device == 'android',
                'gaia': device == 'firefoxos'}
