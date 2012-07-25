from django.conf.urls.defaults import include, patterns, url

from tastypie.api import Api
from mkt.search.api import SearchResource
from mkt.api.resources import (AppResource, CategoryResource,
                               DeviceTypeResource, PreviewResource,
                               StatusResource, ValidationResource)

api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(DeviceTypeResource())
api.register(SearchResource())
api.register(PreviewResource())
api.register(StatusResource())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
