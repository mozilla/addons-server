from mkt.api.base import MarketplaceModelResource
from versions.models import Version


class VersionResource(MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        queryset = Version.objects.all()
        fields = ['version']
        allowed_methods = []
        resource_name = 'version'
        include_resource_uri = False

    def dehydrate(self, bundle):
        bundle.data['latest'] = bundle.obj.addon.latest_version == bundle.obj
        bundle.data['name'] = bundle.data['version']
        del bundle.data['version']
        return bundle
