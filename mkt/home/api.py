from tastypie.authorization import ReadOnlyAuthorization

from mkt import regions
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.resources import AppResource, CategoryResource
from mkt.home.forms import Featured
from mkt.webapps.models import Webapp


class HomepageResource(CORSResource, MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        authorization = ReadOnlyAuthorization()
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        object_class = dict
        resource_name = 'page'

    def get_resource_uri(self, bundle):
        return None

    def get_list(self, request, **kwargs):
        form = Featured(request.GET,
                        region=getattr(request, 'REGION',
                                       regions.WORLDWIDE).slug)
        if not form.is_valid():
            raise self.form_errors(form)

        data = form.as_featured()
        # By default the home page has no category.
        data['cat'] = None
        # Regardless of the limit, we will override that.
        data['limit'] = 9 if data['mobile'] else 12

        cat = CategoryResource()
        featured = Webapp.featured(**data)

        return self.create_response(request, {
            'categories': cat.dehydrate_objects(cat.obj_get_list()),
            'featured': AppResource().dehydrate_objects(featured)
        })


class FeaturedHomeResource(AppResource):

    class Meta(AppResource.Meta):
        allowed_methods = []
        authorization = ReadOnlyAuthorization()
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        resource_name = 'featured'

    def get_resource_uri(self, bundle):
        return None

    def obj_get_list(self, request=None, **kwargs):
        form = Featured(request.GET,
                        region=getattr(request, 'REGION',
                                       regions.WORLDWIDE).slug)
        if not form.is_valid():
            raise self.form_errors(form)

        return Webapp.featured(**form.as_featured())
