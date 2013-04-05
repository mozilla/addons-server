from django.conf import settings
from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.api.resources import (AppResource, CategoryResource, PreviewResource,
                               StatusResource, ValidationResource)
from mkt.ratings.resources import RatingResource
from mkt.search.api import SearchResource, WithCreaturedResource

from tastypie_services.urls import services

api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(PreviewResource())
api.register(WithCreaturedResource())
api.register(SearchResource())
api.register(StatusResource())
api.register(RatingResource())


urls = [url(r'^', include(api.urls)),]
if settings.ALLOW_TASTYPIE_SERVICES:
    urls.append(url(r'^', include(services.urls)))

urlpatterns = patterns('', *urls)
