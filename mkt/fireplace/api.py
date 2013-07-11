from mkt.api.resources import AppResource as BaseAppResource


class AppResource(BaseAppResource):

    class Meta(BaseAppResource.Meta):
        list_allowed_methods = []
        detail_allowed_methods = ['get']

    upsold = None

    def dehydrate_extra(self, bundle):
        pass
