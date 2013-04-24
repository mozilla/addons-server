from django.conf import settings
from django.conf.urls import include, patterns, url

from tastypie.api import Api
from tastypie_services.services import (ErrorResource, SettingsResource)
from mkt.api.base import handle_500
from mkt.api.resources import (AppResource, CarrierResource, CategoryResource,
                               ConfigResource, PreviewResource, RegionResource,
                               StatusResource, ValidationResource)
from mkt.ratings.resources import RatingResource
from mkt.search.api import SearchResource, WithFeaturedResource
from mkt.stats.api import GlobalStatsResource


api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())
api.register(CategoryResource())
api.register(PreviewResource())
api.register(WithFeaturedResource())
api.register(SearchResource())
api.register(StatusResource())
api.register(RatingResource())

stats_api = Api(api_name='stats')
stats_api.register(GlobalStatsResource())

services = Api(api_name='services')
services.register(ConfigResource())
services.register(RegionResource())
services.register(CarrierResource())

if settings.ALLOW_TASTYPIE_SERVICES:
    services.register(ErrorResource(set_handler=handle_500))
    if getattr(settings, 'CLEANSED_SETTINGS_ACCESS', False):
        services.register(SettingsResource())


urlpatterns = patterns('',
    url(r'^', include(api.urls)),
    url(r'^', include(stats_api.urls)),
    url(r'^', include(services.urls))
)
