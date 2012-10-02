from tastypie.serializers import Serializer

import amo
from amo.helpers import absolutify

import mkt
from mkt.api.base import MarketplaceResource
from mkt.search.views import _get_query, _filter_search
from mkt.search.forms import ApiSearchForm
from mkt.webapps.models import Webapp


class SearchResource(MarketplaceResource):

    class Meta:
        available_methods = []
        list_available_methods = ['get', 'post']
        fields = ['id', 'name', 'description', 'premium_type', 'slug',
                  'summary']
        object_class = Webapp
        resource_name = 'search'
        serializer = Serializer(formats=['json'])

    def get_resource_uri(self, bundle):
        # At this time we don't have an API to the Webapp details.
        return None

    def get_list(self, request=None, **kwargs):
        form = ApiSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)

        # Search specific processing of the results.
        region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
        qs = _get_query(region, request.GAIA)
        qs = _filter_search(qs, form.cleaned_data, region=region)
        res = amo.utils.paginate(request, qs)

        # Rehydrate the results as per tastypie.
        bundles = [self.build_bundle(obj=obj, request=request)
                   for obj in res.object_list]
        objs = [self.full_dehydrate(bundle) for bundle in bundles]
        # This isn't as quite a full as a full TastyPie meta object,
        # but at least it's namespaced that way and ready to expand.
        return self.create_response(request, {'objects': objs, 'meta': {}})

    def dehydrate_slug(self, bundle):
        return bundle.obj.app_slug

    def dehydrate(self, bundle):
        for size in amo.ADDON_ICON_SIZES:
            bundle.data['icon_url_%s' % size] = bundle.obj.get_icon_url(size)
        bundle.data['absolute_url'] = absolutify(bundle.obj.get_detail_url())
        return bundle
