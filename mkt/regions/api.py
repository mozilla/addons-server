from mkt.api.base import MarketplaceResource


class RegionResource(MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        allowed_methods = []
        fields = ('name', 'slug', 'mcc', 'adolescent', 'supports_carrier_billing')
        resource_name = 'region'
        include_resource_uri = False

    def full_dehydrate(self, bundle):
        bundle.data = {}
        for field in self._meta.fields:
            bundle.data[field] = getattr(bundle.obj, field)
        return bundle
