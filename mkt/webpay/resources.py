from mkt.api.base import MarketplaceResource
from market.models import Price

from tastypie import fields


class PriceResource(MarketplaceResource):
    prices = fields.ListField(attribute='prices', readonly=True)

    class Meta:
        queryset = Price.objects.filter(active=True)
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        resource_name = 'prices'
        fields = ['name']

    def dehydrate_prices(self, bundle):
        return bundle.obj.prices(provider=bundle.request.GET
                                                .get('provider', None))
