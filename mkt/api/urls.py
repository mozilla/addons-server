from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.api.resources import (AppResource, CategoryResource, PreviewResource,
                               StatusResource, ValidationResource)
from mkt.ratings.resources import RatingResource
from mkt.search.api import SearchResource


api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(PreviewResource())
api.register(SearchResource())
api.register(StatusResource())
api.register(RatingResource())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
