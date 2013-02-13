from django.conf.urls import include, patterns, url

from tastypie.api import Api
from mkt.search.api import SearchResource
from mkt.api.resources import (AppResource, CategoryResource, PreviewResource,
                               RatingResource, StatusResource,
                               ValidationResource)

api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(SearchResource())
api.register(PreviewResource())
api.register(StatusResource())
api.register(RatingResource())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
